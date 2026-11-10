
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.lead import Lead


def normalize_email(value: str | None) -> str | None:
    return value.strip().casefold() if value and value.strip() else None


def normalize_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None

    # Ignore formatting differences such as spaces, +, and hyphens.
    digits = "".join(character for character in value if character.isdigit())
    return digits or None


def classify_import_rows(
    rows: list[dict],
    db: Session,
    user_id: int | None = None,
) -> list[dict]:
    """Classify each import row as create, update, or review.

    Matching priority:
    1. Normalized email (primary key)
    2. Normalized phone (fallback only when email is absent/invalid and
       the phone match is unambiguous - exactly one existing lead)

    Only matches against leads owned by the specified user_id (if provided).
    """
    # --- Collect emails for email-based matching ---
    emails = {
        normalize_email(row.get("lead", {}).get("email"))
        for row in rows
        if not row.get("errors")
        and normalize_email(row.get("lead", {}).get("email"))
    }

    # --- Collect phones for phone-based fallback matching ---
    phones = {
        normalize_phone(row.get("lead", {}).get("phone"))
        for row in rows
        if not row.get("errors")
        and not normalize_email(row.get("lead", {}).get("email"))
        and normalize_phone(row.get("lead", {}).get("phone"))
    }

    existing_by_email: dict[str, Lead] = {}
    existing_by_phone: dict[str, Lead] = {}
    ambiguous_phones: set[str] = set()

    if emails:
        statement = select(Lead).where(
            func.lower(Lead.email).in_(emails)
        )
        if user_id is not None:
            statement = statement.where(Lead.user_id == user_id)
        matches = db.scalars(statement).all()
        existing_by_email = {
            normalize_email(lead.email): lead
            for lead in matches
        }

    if phones:
        # Build a phone->lead map for unambiguous lookups.
        # We query all leads with matching phones and check uniqueness.
        phone_list = list(phones)
        statement = select(Lead).where(
            or_(*[
                func.lower(Lead.phone).like(f"%{p}%") for p in phone_list
            ])
        )
        if user_id is not None:
            statement = statement.where(Lead.user_id == user_id)
        phone_matches = db.scalars(statement).all()

        # Map normalized phone -> lead, but only if unambiguous (one lead per phone)
        phone_to_leads: dict[str, list[Lead]] = {}
        for lead in phone_matches:
            np = normalize_phone(lead.phone)
            if np:
                phone_to_leads.setdefault(np, []).append(lead)

        for np, leads in phone_to_leads.items():
            if len(leads) == 1:
                existing_by_phone[np] = leads[0]
            else:
                ambiguous_phones.add(np)

    classifications = []

    for row in rows:
        lead_data = row.get("lead", {})
        review_reasons = []

        if row.get("errors"):
            classifications.append({
                **row,
                "action": "review",
                "existing_lead_id": None,
                "review_reasons": [
                    "The row contains validation errors."
                ],
                "preserve_existing_fields": [],
            })
            continue

        email = normalize_email(lead_data.get("email"))
        phone = normalize_phone(lead_data.get("phone"))

        existing = None
        match_method = None

        # 1. Try email match first
        if email:
            existing = existing_by_email.get(email)
            match_method = "email"

        # 2. Fallback to phone match only if email is absent/invalid
        #    and phone match is unambiguous. An ambiguous phone (matched
        #    by more than one existing lead) is never silently used:
        #    the row goes to review instead of being created as a duplicate.
        if not existing and phone and phone in ambiguous_phones:
            review_reasons.append(
                "Multiple existing leads share this phone number, "
                "so the phone match is ambiguous."
            )
        elif not existing and phone:
            existing = existing_by_phone.get(phone)
            match_method = "phone"

        if existing:
            imported_phone = normalize_phone(lead_data.get("phone"))
            existing_phone = normalize_phone(existing.phone)

            if match_method == "email":
                # Phone conflict check for email matches
                if (
                    imported_phone
                    and existing_phone
                    and imported_phone != existing_phone
                ):
                    review_reasons.append(
                        "The imported phone number differs from "
                        "the existing lead's phone number."
                    )

            preserve_fields = [
                field
                for field in ("name", "email", "company", "phone", "location")
                if not lead_data.get(field)
            ]

            classifications.append({
                **row,
                "action": "review" if review_reasons else "update",
                "existing_lead_id": existing.id,
                "review_reasons": review_reasons,
                "preserve_existing_fields": preserve_fields,
                "matched_by": match_method,
            })
        elif review_reasons:
            classifications.append({
                **row,
                "action": "review",
                "existing_lead_id": None,
                "review_reasons": review_reasons,
                "preserve_existing_fields": [],
                "matched_by": None,
            })
        else:
            classifications.append({
                **row,
                "action": "create",
                "existing_lead_id": None,
                "review_reasons": [],
                "preserve_existing_fields": [],
                "matched_by": None,
            })

    return classifications
