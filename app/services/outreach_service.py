import csv
import io
import re
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import pandas as pd
from openpyxl import load_workbook

from app.db.mongo import get_mongo_db
from app.repositories.report_repository import ReportRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.batch_repository import BatchRepository
from app.repositories.audit_repository import AuditRepository


ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_ROWS = 250_000

# Canonical Channel values
VALID_CHANNELS = {
    "phone": ["phone", "call", "calling", "mobile", "telephone", "voice"],
    "whatsapp": ["whatsapp", "wa", "wapp"],
    "linkedin": ["linkedin", "li"],
    "instagram": ["instagram", "ig", "insta"],
    "facebook": ["facebook", "fb"],
    "email": ["email", "mail"],
    "other": ["other", "website", "sms", "text"],
}

# Canonical Contact Statuses
CONTACT_STATUS_MAP = {
    "not_contacted": ["not contacted", "uncontacted", "new", "pending", "none", "not called", "unreached"],
    "attempted": ["attempted", "trying", "calling", "queued", "dialed", "no answer", "busy", "voicemail"],
    "contacted": ["contacted", "connected", "reached", "called", "spoke", "in progress", "qualified", "pitched"],
    "delivered": ["delivered", "sent", "message sent", "dropped"],
    "replied": ["replied", "responded", "answered", "chatted"],
}

# Canonical Interest Statuses
INTEREST_STATUS_MAP = {
    "interested": [
        "interested", "positive", "hot", "warm", "won", "qualified", "closed won",
        "wants details", "requested quotation", "demo booked", "meeting scheduled"
    ],
    "potentially_interested": [
        "potentially interested", "lukewarm", "follow up later", "thinking", "maybe",
        "evaluating", "reviewing", "interested later", "send info"
    ],
    "not_interested": [
        "not interested", "declined", "cold", "lost", "closed lost", "rejected",
        "unqualified", "not a fit", "opted out", "unsubscribe", "do not call", "dnc"
    ],
    "awaiting_response": [
        "awaiting response", "waiting for reply", "pending reply", "no response",
        "unresponsive", "follow up", "contacted"
    ],
    "unclear": ["unclear", "ambiguous", "mixed", "confused"],
    "invalid_contact": [
        "invalid contact", "wrong number", "bounced", "invalid email",
        "disconnected", "out of service"
    ],
    "unknown": ["unknown", "new", ""]
}

# Standard Field Aliases
HEADER_ALIASES = {
    "id": {"id", "lead id", "lead_id", "record id", "record_id", "_id", "prospect id"},
    "name": {"name", "full name", "contact name", "lead name", "prospect name", "client name"},
    "email": {"email", "email address", "contact email", "work email", "e mail"},
    "phone": {"phone", "phone number", "mobile", "mobile number", "contact number", "cell", "telephone"},
    "company": {"company", "company name", "organization", "organisation", "business name", "account"},
    "location": {"location", "city", "region", "state", "country", "address"},
    "channel": {"channel", "contact channel", "platform", "outreach channel", "medium", "source"},
    "employee": {"sales representative", "sales rep", "rep", "agent", "employee", "owner", "assigned to"},
    "status": {"status", "lead status", "contact status", "outreach status", "stage"},
    "interest": {"interest", "interest status", "response", "outcome", "lead response"},
    "deal_value": {"deal value", "deal_value", "budget", "amount", "value", "expected revenue"},
    "follow_up_date": {"follow up date", "follow_up_date", "follow up", "next contact date", "due date"},
    "notes": {"notes", "comment", "comments", "remarks", "response notes"},
}


def normalize_string(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    val = str(email).strip().lower()
    if "@" in val and "." in val:
        return val
    return None


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    cleaned = "".join(c for c in str(phone) if c.isdigit() or c == "+")
    digits = "".join(c for c in cleaned if c.isdigit())
    if len(digits) >= 7:
        return cleaned
    return None


def detect_channel(val: Optional[str]) -> str:
    if not val:
        return "unknown"
    val_lower = str(val).strip().lower()
    for canonical, aliases in VALID_CHANNELS.items():
        if any(alias in val_lower for alias in aliases):
            return canonical
    return "other"


def detect_contact_status(val: Optional[str]) -> str:
    if not val:
        return "not_contacted"
    val_lower = str(val).strip().lower()
    for canonical, aliases in CONTACT_STATUS_MAP.items():
        if val_lower in aliases:
            return canonical
    return "not_contacted"


def detect_interest_status(val: Optional[str]) -> str:
    if not val:
        return "unknown"
    val_lower = str(val).strip().lower()
    for canonical, aliases in INTEREST_STATUS_MAP.items():
        if val_lower in aliases:
            return canonical
    return "unknown"


def sanitize_for_export(val: Any) -> Any:
    """Prevent CSV/Excel Formula Injection by escaping leading =, +, -, @, \\t, \\r."""
    if isinstance(val, str) and val:
        if val[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{val}"
    return val


class OutreachImportService:
    def __init__(self):
        self.db = get_mongo_db()
        self.report_repo = ReportRepository(self.db)
        self.lead_repo = LeadRepository(self.db)
        self.batch_repo = BatchRepository(self.db)
        self.audit_repo = AuditRepository(self.db)

    def parse_file(self, filename: str, content: bytes) -> Tuple[List[str], List[Dict[str, str]]]:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError("Supported formats are CSV and XLSX only.")

        if not content:
            raise ValueError("Uploaded file is empty.")

        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds limit of {MAX_FILE_SIZE // (1024*1024)}MB.")

        try:
            if ext == ".csv":
                # Try UTF-8 first, fallback to latin-1
                try:
                    df = pd.read_csv(
                        io.BytesIO(content),
                        dtype=str,
                        keep_default_na=False,
                        encoding="utf-8",
                    )
                except UnicodeDecodeError:
                    df = pd.read_csv(
                        io.BytesIO(content),
                        dtype=str,
                        keep_default_na=False,
                        encoding="latin-1",
                    )
            else:
                df = pd.read_excel(
                    io.BytesIO(content),
                    dtype=str,
                    keep_default_na=False,
                    engine="openpyxl",
                )
        except Exception as e:
            raise ValueError(f"Unable to parse spreadsheet: {str(e)}")

        if df.empty and len(df.columns) == 0:
            raise ValueError("The spreadsheet contains no data or column headers.")

        if len(df) > MAX_ROWS:
            raise ValueError(f"Spreadsheet row count ({len(df)}) exceeds maximum allowed ({MAX_ROWS}).")

        # Clean column headers
        raw_headers = [str(col).strip() for col in df.columns]
        headers = []
        for i, h in enumerate(raw_headers):
            if not h or h.lower().startswith("unnamed:"):
                headers.append(f"Column_{i+1}")
            else:
                headers.append(h)

        df.columns = headers
        df = df.fillna("")

        rows = df.to_dict(orient="records")
        clean_rows = []
        for r in rows:
            clean_row = {str(k): str(v).strip() for k, v in r.items()}
            # Skip completely empty rows
            if any(val for val in clean_row.values()):
                clean_rows.append(clean_row)

        return headers, clean_rows

    def map_columns(self, headers: List[str]) -> Dict[str, str]:
        """Map raw headers to canonical concepts, retaining unmapped headers as extra attributes."""
        mapping: Dict[str, str] = {}
        used_canonical: Set[str] = set()

        for header in headers:
            norm_header = re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()
            matched = None
            for canonical, aliases in HEADER_ALIASES.items():
                if norm_header in aliases and canonical not in used_canonical:
                    matched = canonical
                    used_canonical.add(canonical)
                    break
            mapping[header] = matched if matched else "__attribute__"

        return mapping

    def preview_import(
        self,
        workspace_id: str,
        filename: str,
        content: bytes,
        target_report_id: Optional[str] = None,
        created_by: str = "",
    ) -> Dict[str, Any]:
        headers, rows = self.parse_file(filename, content)
        mapping = self.map_columns(headers)

        # Collect candidate IDs, Emails, Phones for matching
        candidate_ids = []
        candidate_emails = []
        candidate_phones = []

        extracted_rows = []
        for idx, row in enumerate(rows, start=1):
            extracted = {
                "row_number": idx,
                "raw": row,
                "extracted": {},
                "errors": [],
                "warnings": [],
            }
            # Extract standard fields
            for col, canonical in mapping.items():
                val = row.get(col, "").strip()
                if canonical != "__attribute__" and val:
                    extracted["extracted"][canonical] = val

            # Check matching keys
            rid = extracted["extracted"].get("id")
            if rid:
                candidate_ids.append(rid)

            remail = normalize_email(extracted["extracted"].get("email"))
            if remail:
                candidate_emails.append(remail)

            rphone = normalize_phone(extracted["extracted"].get("phone"))
            if rphone:
                candidate_phones.append(rphone)

            extracted_rows.append(extracted)

        # Query existing matches if target_report_id is specified
        existing_matches = {
            "by_id": {},
            "by_email": {},
            "by_phone": {},
        }
        if target_report_id:
            existing_matches = self.lead_repo.find_matches_in_report(
                workspace_id=workspace_id,
                report_id=target_report_id,
                candidate_ids=candidate_ids,
                candidate_emails=candidate_emails,
                candidate_phones=candidate_phones,
            )

        # Classify each row
        summary = {
            "create": 0,
            "update": 0,
            "unchanged": 0,
            "review": 0,
            "error": 0,
        }

        classified_rows = []
        for r in extracted_rows:
            ext = r["extracted"]
            row_id = ext.get("id")
            row_email = normalize_email(ext.get("email"))
            row_phone = normalize_phone(ext.get("phone"))

            action = "create"
            matched_lead_id = None
            matched_by = None
            review_reasons = []

            # 1. Match by stable ID
            if row_id and row_id in existing_matches["by_id"]:
                matched_leads = existing_matches["by_id"][row_id]
                if len(matched_leads) == 1:
                    matched_lead_id = matched_leads[0]["id"]
                    matched_by = "id"
                    action = "update"
                else:
                    action = "review"
                    review_reasons.append("Multiple existing records match this Record ID.")

            # 2. Match by email
            elif row_email and row_email in existing_matches["by_email"]:
                matched_leads = existing_matches["by_email"][row_email]
                if len(matched_leads) == 1:
                    matched_lead_id = matched_leads[0]["id"]
                    matched_by = "email"
                    action = "update"
                else:
                    action = "review"
                    review_reasons.append("Multiple existing records match this email address.")

            # 3. Match by phone (fallback only if email not provided)
            elif not row_email and row_phone and row_phone in existing_matches["by_phone"]:
                matched_leads = existing_matches["by_phone"][row_phone]
                if len(matched_leads) == 1:
                    matched_lead_id = matched_leads[0]["id"]
                    matched_by = "phone"
                    action = "update"
                else:
                    action = "review"
                    review_reasons.append("Multiple existing records match this phone number.")

            # Validation checks
            name_val = ext.get("name")
            if not name_val and not row_email and not row_phone:
                action = "review"
                review_reasons.append("Row has no contact identifier (missing name, email, and phone).")

            summary[action] = summary.get(action, 0) + 1

            classified_rows.append({
                "row_number": r["row_number"],
                "action": action,
                "matched_lead_id": matched_lead_id,
                "matched_by": matched_by,
                "extracted": ext,
                "raw": r["raw"],
                "review_reasons": review_reasons,
            })

        # Suggest report title
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stem = Path(filename).stem.replace("_", " ").replace("-", " ").title()
        suggested_title = f"{stem} ({date_str})"

        # Persist preview batch in MongoDB
        batch = self.batch_repo.create_batch(
            workspace_id=workspace_id,
            report_id=target_report_id or "pending",
            filename=filename,
            file_size=len(content),
            created_by=created_by,
            summary=summary,
            status="preview_ready",
            plan={
                "mapping": mapping,
                "headers": headers,
                "suggested_title": suggested_title,
                "total_rows": len(rows),
                "summary": summary,
                "rows": classified_rows,
            },
        )

        return {
            "batch_id": batch["id"],
            "filename": filename,
            "file_size": len(content),
            "total_rows": len(rows),
            "suggested_title": suggested_title,
            "detected_columns": [
                {
                    "header": h,
                    "mapping": mapping.get(h, "__attribute__"),
                    "is_recognized": mapping.get(h) != "__attribute__",
                }
                for h in headers
            ],
            "sample_rows": [r["raw"] for r in classified_rows[:8]],
            "summary": summary,
        }

    def commit_import(
        self,
        workspace_id: str,
        batch_id: str,
        title: Optional[str] = None,
        description: str = "",
        target_report_id: Optional[str] = None,
        created_by: str = "",
    ) -> Dict[str, Any]:
        batch = self.batch_repo.get_batch(workspace_id, batch_id)
        if not batch:
            raise ValueError("Import batch not found.")

        if batch.get("status") == "completed":
            return {
                "batch_id": batch_id,
                "status": "completed",
                "already_committed": True,
                "summary": batch.get("summary", {}),
                "report_id": batch.get("report_id"),
            }

        plan = batch.get("plan", {})
        rows = plan.get("rows", [])
        if not rows:
            raise ValueError("Batch has no rows to commit.")

        # Resolve or create target report
        if target_report_id:
            report = self.report_repo.get_report(workspace_id, target_report_id)
            if not report:
                raise ValueError("Target Outreach Report does not exist.")
            final_report_id = target_report_id
        else:
            rep_title = title.strip() if title and title.strip() else plan.get("suggested_title", "Outreach Report")
            new_report = self.report_repo.create_report(
                workspace_id=workspace_id,
                title=rep_title,
                description=description,
                created_by=created_by,
                source_file=batch.get("filename"),
            )
            final_report_id = new_report["id"]

        now_str = datetime.now(timezone.utc).isoformat()
        today_str = datetime.now(timezone.utc).date().isoformat()

        committed_creates = 0
        committed_updates = 0
        skipped_reviews = 0

        for r in rows:
            action = r.get("action")
            raw_data = r.get("raw", {})
            ext = r.get("extracted", {})

            if action == "review":
                skipped_reviews += 1
                continue

            # Contact status & Interest status
            status_raw = ext.get("status")
            interest_raw = ext.get("interest")
            
            contact_status = detect_contact_status(status_raw)
            interest_status = detect_interest_status(interest_raw or status_raw)

            # Channel & Employee
            channel_val = detect_channel(ext.get("channel") or ext.get("phone"))
            employee_val = ext.get("employee") or None

            # Follow up date & status
            fu_date_val = ext.get("follow_up_date") or None
            fu_status = "not_required"
            if fu_date_val:
                if fu_date_val < today_str:
                    fu_status = "overdue"
                elif fu_date_val == today_str:
                    fu_status = "due"
                else:
                    fu_status = "scheduled"
            elif interest_status in ["interested", "potentially_interested"]:
                fu_status = "suggested"
            elif contact_status == "contacted" and interest_status == "awaiting_response":
                fu_status = "suggested"

            # Deal value
            deal_val = None
            if ext.get("deal_value"):
                try:
                    deal_val = float(re.sub(r"[^\d.]", "", str(ext["deal_value"])))
                except ValueError:
                    pass

            if action == "create":
                lead_doc = {
                    "_id": f"lead_{uuid.uuid4().hex[:14]}",
                    "workspace_id": workspace_id,
                    "report_id": final_report_id,
                    "attributes": dict(raw_data),
                    "normalized": {
                        "name": ext.get("name") or raw_data.get("Full Name") or raw_data.get("Name"),
                        "email": normalize_email(ext.get("email")),
                        "phone": normalize_phone(ext.get("phone")),
                        "company": ext.get("company") or raw_data.get("Company Name") or raw_data.get("Company"),
                        "location": ext.get("location") or raw_data.get("City") or raw_data.get("Location"),
                        "deal_value": deal_val,
                    },
                    "outcome": {
                        "contact_status": contact_status,
                        "interest_status": interest_status,
                        "source": "imported",
                        "original_status": status_raw,
                        "original_interest": interest_raw,
                    },
                    "channel": channel_val,
                    "assigned_employee": employee_val,
                    "follow_up": {
                        "status": fu_status,
                        "due_date": fu_date_val,
                        "reason": "Imported follow-up" if fu_date_val else "Initial interest recommendation",
                        "notes": ext.get("notes") or "",
                        "completed_at": None,
                        "assigned_to": employee_val,
                    },
                    "timestamps": {
                        "created_at": now_str,
                        "updated_at": now_str,
                        "first_seen_at": now_str,
                        "last_imported_at": now_str,
                    },
                    "import_provenance": [batch_id],
                    "history": [
                        {
                            "action": "imported",
                            "batch_id": batch_id,
                            "timestamp": now_str,
                            "contact_status": contact_status,
                            "interest_status": interest_status,
                        }
                    ],
                }
                self.lead_repo.create_lead(lead_doc)
                committed_creates += 1

            elif action == "update":
                matched_id = r.get("matched_lead_id")
                existing = self.lead_repo.get_lead_by_id(workspace_id, matched_id)
                if not existing:
                    continue

                # Merge attributes: DO NOT overwrite with blank cells!
                merged_attrs = dict(existing.get("attributes", {}))
                for k, v in raw_data.items():
                    if v and str(v).strip():
                        merged_attrs[k] = v

                # Merge normalized
                merged_norm = dict(existing.get("normalized", {}))
                for norm_key in ["name", "email", "phone", "company", "location", "deal_value"]:
                    val = ext.get(norm_key)
                    if val is not None and str(val).strip():
                        if norm_key == "email":
                            merged_norm["email"] = normalize_email(val) or merged_norm.get("email")
                        elif norm_key == "phone":
                            merged_norm["phone"] = normalize_phone(val) or merged_norm.get("phone")
                        elif norm_key == "deal_value":
                            if deal_val is not None:
                                merged_norm["deal_value"] = deal_val
                        else:
                            merged_norm[norm_key] = val

                # Determine if outcome changed
                old_outcome = existing.get("outcome", {})
                new_outcome = dict(old_outcome)
                history_entries = []

                if status_raw or interest_raw:
                    if contact_status != old_outcome.get("contact_status") or interest_status != old_outcome.get("interest_status"):
                        new_outcome["contact_status"] = contact_status
                        new_outcome["interest_status"] = interest_status
                        new_outcome["source"] = "imported_update"
                        history_entries.append({
                            "action": "status_updated_via_import",
                            "batch_id": batch_id,
                            "timestamp": now_str,
                            "old": old_outcome,
                            "new": new_outcome,
                        })

                # Follow-up preservation / update
                existing_fu = dict(existing.get("follow_up", {}))
                if fu_date_val:
                    existing_fu["due_date"] = fu_date_val
                    existing_fu["status"] = fu_status

                update_fields = {
                    "attributes": merged_attrs,
                    "normalized": merged_norm,
                    "outcome": new_outcome,
                    "follow_up": existing_fu,
                    "timestamps.last_imported_at": now_str,
                    "timestamps.updated_at": now_str,
                }
                if employee_val:
                    update_fields["assigned_employee"] = employee_val
                if channel_val != "unknown":
                    update_fields["channel"] = channel_val

                # Execute update with history push
                query = {"workspace_id": workspace_id, "_id": existing["_id"]}
                update_op: Dict[str, Any] = {
                    "$set": update_fields,
                    "$addToSet": {"import_provenance": batch_id},
                }
                if history_entries:
                    update_op["$push"] = {"history": {"$each": history_entries}}

                self.db.leads.update_one(query, update_op)
                committed_updates += 1

        # Recalculate metrics on the report
        metrics = self.report_repo.recalculate_metrics(workspace_id, final_report_id)

        # Update batch status
        final_summary = {
            "create": committed_creates,
            "update": committed_updates,
            "review_skipped": skipped_reviews,
            "total_processed": committed_creates + committed_updates + skipped_reviews,
        }
        self.batch_repo.update_batch_status(
            workspace_id=workspace_id,
            batch_id=batch_id,
            status="completed",
            summary=final_summary,
        )

        # Audit event
        self.audit_repo.log_event(
            workspace_id=workspace_id,
            entity_type="outreach_report",
            entity_id=final_report_id,
            action="import_committed",
            actor_id=created_by,
            details=final_summary,
        )

        return {
            "batch_id": batch_id,
            "report_id": final_report_id,
            "status": "completed",
            "summary": final_summary,
            "metrics": metrics,
        }
