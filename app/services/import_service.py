
"""Business logic for the spreadsheet-to-CRM import workflow.

The import is split into server-managed stages so the client never
supplies the final write payload:

1. Preview (parse + store raw rows server-side)
2. Plan (validate + match + detect conflicts, using stored rows)
3. Commit (transactional write of the approved plan)

Keeping the parsed rows and computed plan server-side is what makes the
confirm step idempotent and safe from stale or tampered client data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_session import ImportSession
from app.models.lead import Lead
from app.models.custom_field import CustomFieldDefinition
from app.models.lead_custom_field_value import LeadCustomFieldValue
from app.schemas.import_session import ImportPlanRequest
from app.services.lead_import_validator import (
    normalize_email,
    validate_import_rows,
)
from app.services.lead_import_matcher import classify_import_rows

SESSION_TTL_MINUTES = 60

# Actions that may be committed automatically. "review" rows require
# manual resolution and are never written by the commit endpoint.
COMMITTABLE_ACTIONS = {"create", "update"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at() -> datetime:
    return _now() + timedelta(minutes=SESSION_TTL_MINUTES)


def _is_expired(session: ImportSession) -> bool:
    """Check whether an import session's expiry has passed."""
    if not session.expires_at:
        return False
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < _now()


def create_import_session(
    filename: str,
    raw_rows: list[dict[str, object]],
    db: Session,
    user_id: int,
) -> ImportSession:
    """Create a pending import session storing raw rows server-side."""
    session = ImportSession(
        session_key=str(uuid.uuid4()),
        filename=filename,
        user_id=user_id,
        status="pending",
        import_plan={
            "raw_rows": raw_rows,
            "total_rows": len(raw_rows),
        },
        expires_at=_expires_at(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_import_session(
    session_key: str,
    db: Session,
    user_id: int | None = None,
) -> ImportSession | None:
    """Fetch an import session by its idempotency key.

    If user_id is provided, only sessions owned by that user are returned.
    """
    query = db.query(ImportSession).filter(
        ImportSession.session_key == session_key
    )
    if user_id is not None:
        query = query.filter(ImportSession.user_id == user_id)
    return query.first()


def build_import_plan(
    session_key: str,
    request: ImportPlanRequest,
    db: Session,
    user_id: int,
) -> dict[str, Any]:
    """Validate the mapping and produce the full import plan (Stages C-E).

    The raw spreadsheet rows are read from the persisted session, never
    from the client, so a tampered client cannot inject forged rows.
    Only matches against leads owned by the specified user.
    """
    session = get_import_session(session_key, db, user_id=user_id)
    if not session:
        raise ValueError("Import session not found.")
    if session.status != "pending":
        raise ValueError(f"Import session is not pending (status={session.status}).")
    if _is_expired(session):
        session.status = "expired"
        db.commit()
        raise ValueError("Import session has expired.")

    raw_rows: list[dict[str, object]] = session.import_plan.get("raw_rows", [])

    # --- Stage C: validate rows (backend-authoritative) -------------------
    validation = validate_import_rows(
        raw_rows, request.mapping, request.custom_fields
    )

    # --- Stage D + E: match existing leads and detect conflicts -----------
    classifications = classify_import_rows(
        validation["rows"], db, user_id=user_id
    )

    # Build the plan rows, merging validation errors with classifications.
    plan_rows = []
    summary = {"create": 0, "update": 0, "review": 0, "skip": 0, "error": 0}

    for classification in classifications:
        row_number = classification.get("row_number")
        action = classification.get("action", "review")
        summary[action] = summary.get(action, 0) + 1

        plan_rows.append({
            "row_number": row_number,
            "action": action,
            "existing_lead_id": classification.get("existing_lead_id"),
            "lead": classification.get("lead", {}),
            "custom_values": classification.get("custom_values", {}),
            "review_reasons": classification.get("review_reasons", []),
            "preserve_existing_fields": classification.get(
                "preserve_existing_fields", []
            ),
            "errors": classification.get("errors", []),
        })

    # Persist the computed plan so commit can reuse it exactly.
    session.import_plan = {
        "raw_rows": raw_rows,
        "mapping": request.mapping,
        "custom_fields": request.custom_fields,
        "total_rows": len(raw_rows),
        "rows": plan_rows,
        "summary": summary,
    }
    db.commit()

    return {
        "session_key": session.session_key,
        "filename": session.filename,
        "total_rows": len(raw_rows),
        "summary": summary,
        "rows": plan_rows,
        "expires_at": session.expires_at,
    }


def commit_import(
    session_key: str,
    db: Session,
    user_id: int,
) -> dict[str, Any]:
    """Commit the approved import plan in a single transaction (Stage G).

    Only "create" and "update" rows are written. "review" rows are skipped.
    The operation is idempotent: a completed session is never re-imported.
    Only the session owner may commit.
    """
    session = get_import_session(session_key, db, user_id=user_id)
    if not session:
        raise ValueError("Import session not found.")
    if session.status == "completed":
        return _build_commit_response(session, db, already_committed=True)
    if session.status != "pending":
        raise ValueError(
            f"Import session cannot be committed (status={session.status})."
        )
    if _is_expired(session):
        session.status = "expired"
        db.commit()
        raise ValueError("Import session has expired.")

    plan = session.import_plan or {}
    rows = plan.get("rows", [])
    custom_fields = plan.get("custom_fields", {})

    created_leads: list[dict[str, Any]] = []
    custom_fields_created = 0
    custom_values_saved = 0

    try:
        for row in rows:
            action = row.get("action")

            if action not in COMMITTABLE_ACTIONS:
                continue

            lead_data = row.get("lead", {})
            custom_values = row.get("custom_values", {})
            existing_lead_id = row.get("existing_lead_id")

            if action == "create":
                lead = Lead(
                    user_id=user_id,
                    name=lead_data.get("name", "").strip(),
                    email=normalize_email(lead_data.get("email")) or "",
                    company=lead_data.get("company", "").strip(),
                    phone=lead_data.get("phone") or None,
                    location=lead_data.get("location") or None,
                    status="New",
                    imported_at=_now(),
                )
                db.add(lead)
                db.flush()
                created_leads.append({
                    "id": lead.id,
                    "name": lead.name,
                    "email": lead.email,
                    "company": lead.company,
                    "action": "create",
                })
                target_lead_id = lead.id
            else:
                # action == "update"
                lead = db.get(Lead, existing_lead_id)
                if not lead or lead.user_id != user_id:
                    continue
                # Preserve existing values where incoming cells are blank.
                if lead_data.get("name"):
                    lead.name = lead_data["name"].strip()
                if lead_data.get("email"):
                    lead.email = normalize_email(lead_data["email"]) or lead.email
                if lead_data.get("company"):
                    lead.company = lead_data["company"].strip()
                if lead_data.get("phone"):
                    lead.phone = lead_data["phone"]
                if lead_data.get("location"):
                    lead.location = lead_data["location"]
                lead.imported_at = _now()
                db.add(lead)
                created_leads.append({
                    "id": lead.id,
                    "name": lead.name,
                    "email": lead.email,
                    "company": lead.company,
                    "action": "update",
                })
                target_lead_id = lead.id

            # --- Custom fields: create/reuse definitions + save values ----
            for source_column, definition in custom_fields.items():
                field_name = (definition.get("name") or source_column).strip()
                field_type = definition.get("type", "text")
                value = custom_values.get(field_name)

                # Blank incoming cells preserve existing values: do not write.
                if value is None or str(value).strip() == "":
                    continue

                # Reuse existing definition case-insensitively, scoped to user.
                field_def = (
                    db.query(CustomFieldDefinition)
                    .filter(
                        CustomFieldDefinition.user_id == user_id,
                        CustomFieldDefinition.name.ilike(field_name),
                        CustomFieldDefinition.is_active.is_(True),
                    )
                    .first()
                )
                if field_def is None:
                    field_def = CustomFieldDefinition(
                        user_id=user_id,
                        name=field_name,
                        field_type=field_type,
                        is_active=True,
                    )
                    db.add(field_def)
                    db.flush()
                    custom_fields_created += 1
                elif field_def.field_type != field_type:
                    # Incompatible type: do not write this value.
                    continue

                # Avoid duplicate values for the same lead and field.
                existing_value = (
                    db.query(LeadCustomFieldValue)
                    .filter(
                        LeadCustomFieldValue.lead_id == target_lead_id,
                        LeadCustomFieldValue.custom_field_id == field_def.id,
                    )
                    .first()
                )
                if existing_value is None:
                    db.add(
                        LeadCustomFieldValue(
                            lead_id=target_lead_id,
                            custom_field_id=field_def.id,
                            value=str(value).strip(),
                        )
                    )
                    custom_values_saved += 1
                else:
                    existing_value.value = str(value).strip()
                    custom_values_saved += 1

        session.status = "completed"
        session.committed_at = _now()
        db.commit()

    except Exception:
        db.rollback()
        session.status = "failed"
        db.commit()
        raise

    return _build_commit_response(
        session,
        db,
        already_committed=False,
        created_leads=created_leads,
        custom_fields_created=custom_fields_created,
        custom_values_saved=custom_values_saved,
    )


def _build_commit_response(
    session: ImportSession,
    db: Session,
    already_committed: bool,
    created_leads: list[dict[str, Any]] | None = None,
    custom_fields_created: int = 0,
    custom_values_saved: int = 0,
) -> dict[str, Any]:
    plan = session.import_plan or {}
    summary = plan.get("summary", {})

    # When the session was already committed, no new work was done in this
    # request, so report zero counts to avoid double-counting.
    if already_committed:
        summary = {"create": 0, "update": 0, "review": 0, "skip": 0, "error": 0}
        created_leads = []
        custom_fields_created = 0
        custom_values_saved = 0

    return {
        "session_key": session.session_key,
        "status": session.status,
        "created": summary.get("create", 0),
        "updated": summary.get("update", 0),
        "reviewed": summary.get("review", 0),
        "skipped": summary.get("skip", 0),
        "errors": summary.get("error", 0),
        "leads": created_leads or [],
        "custom_fields_created": custom_fields_created,
        "custom_values_saved": custom_values_saved,
        "already_committed": already_committed,
    }
