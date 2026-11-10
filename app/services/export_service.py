import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from app.db.mongo import get_mongo_db
from app.repositories.lead_repository import LeadRepository
from app.repositories.report_repository import ReportRepository


def sanitize_export_cell(value: Any) -> Any:
    """Sanitize against CSV/Excel formula injection."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


class ExportService:
    def __init__(self):
        self.db = get_mongo_db()
        self.lead_repo = LeadRepository(self.db)
        self.report_repo = ReportRepository(self.db)

    def generate_report_export(
        self,
        workspace_id: str,
        report_id: str,
        export_format: str = "csv",
        filter_type: Optional[str] = None,
        contact_status: Optional[str] = None,
        interest_status: Optional[str] = None,
        follow_up_status: Optional[str] = None,
        channel: Optional[str] = None,
        employee: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[bytes, str, str]:
        """
        Generate export dataset. Returns (content_bytes, filename, mime_type).
        """
        # Shortcut filters
        if filter_type == "interested":
            interest_status = "interested"
        elif filter_type == "potentially_interested":
            interest_status = "potentially_interested"
        elif filter_type == "not_interested":
            interest_status = "not_interested"
        elif filter_type == "awaiting_response":
            interest_status = "awaiting_response"
        elif filter_type == "not_contacted":
            contact_status = "not_contacted"
        elif filter_type == "follow_up_due":
            follow_up_status = "due"
        elif filter_type == "follow_up_overdue":
            follow_up_status = "overdue"

        leads = self.lead_repo.find_leads(
            workspace_id=workspace_id,
            report_id=report_id,
            contact_status=contact_status,
            interest_status=interest_status,
            follow_up_status=follow_up_status,
            channel=channel,
            employee=employee,
            search=search,
            limit=100_000,
        )

        report = self.report_repo.get_report(workspace_id, report_id)
        rep_title = (report.get("title") or "outreach_report").replace(" ", "_").lower()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Collect all unique attribute keys
        all_attr_keys = []
        for lead in leads:
            attrs = lead.get("attributes") or {}
            for k in attrs.keys():
                if k not in all_attr_keys:
                    all_attr_keys.append(k)

        # Standard export columns (includes stable IDs for re-import compatibility!)
        standard_headers = [
            "Lead ID",
            "Report ID",
            "Name",
            "Email",
            "Phone",
            "Company",
            "Location",
            "Contact Status",
            "Interest Status",
            "Channel",
            "Assigned Employee",
            "Follow-up Status",
            "Follow-up Date",
            "Follow-up Notes",
            "Created At",
            "Updated At",
        ]

        # Extra attribute columns that are not already in standard fields
        extra_headers = [k for k in all_attr_keys if k not in standard_headers]
        headers = standard_headers + extra_headers

        rows = []
        for lead in leads:
            norm = lead.get("normalized") or {}
            outcome = lead.get("outcome") or {}
            fu = lead.get("follow_up") or {}
            ts = lead.get("timestamps") or {}
            attrs = lead.get("attributes") or {}

            row_data = [
                sanitize_export_cell(lead.get("id")),
                sanitize_export_cell(lead.get("report_id")),
                sanitize_export_cell(norm.get("name")),
                sanitize_export_cell(norm.get("email")),
                sanitize_export_cell(norm.get("phone")),
                sanitize_export_cell(norm.get("company")),
                sanitize_export_cell(norm.get("location")),
                sanitize_export_cell(outcome.get("contact_status")),
                sanitize_export_cell(outcome.get("interest_status")),
                sanitize_export_cell(lead.get("channel")),
                sanitize_export_cell(lead.get("assigned_employee")),
                sanitize_export_cell(fu.get("status")),
                sanitize_export_cell(fu.get("due_date")),
                sanitize_export_cell(fu.get("notes")),
                sanitize_export_cell(ts.get("created_at")),
                sanitize_export_cell(ts.get("updated_at")),
            ]

            for extra_k in extra_headers:
                row_data.append(sanitize_export_cell(attrs.get(extra_k, "")))

            rows.append(row_data)

        if export_format.lower() == "xlsx":
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Outreach Results"

            # Style Header
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
            align_center = Alignment(horizontal="center", vertical="center")

            ws.append(headers)
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = align_center

            for row_vals in rows:
                ws.append(row_vals)

            # Auto fit column widths
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

            out_stream = io.BytesIO()
            wb.save(out_stream)
            content = out_stream.getvalue()
            filename = f"{rep_title}_{filter_type or 'all'}_{timestamp}.xlsx"
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return content, filename, mime_type
        else:
            # CSV
            out_stream = io.StringIO()
            writer = csv.writer(out_stream, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(headers)
            writer.writerows(rows)
            content = out_stream.getvalue().encode("utf-8")
            filename = f"{rep_title}_{filter_type or 'all'}_{timestamp}.csv"
            mime_type = "text/csv; charset=utf-8"
            return content, filename, mime_type
