from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_current_active_user
from app.models.user import User
from app.repositories.report_repository import ReportRepository
from app.services.export_service import ExportService

router = APIRouter(prefix="/api/v1/reports", tags=["Export Engine"])

report_repo = ReportRepository()
export_service = ExportService()


@router.get("/{report_id}/export")
def export_report_records(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    format: str = Query("csv", description="csv or xlsx"),
    filter_type: Optional[str] = Query(None, description="all, interested, potentially_interested, not_interested, awaiting_response, not_contacted, follow_up_due, follow_up_overdue"),
    contact_status: Optional[str] = Query(None),
    interest_status: Optional[str] = Query(None),
    follow_up_status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    employee: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )

    content, filename, mime_type = export_service.generate_report_export(
        workspace_id=workspace_id,
        report_id=report_id,
        export_format=format,
        filter_type=filter_type,
        contact_status=contact_status,
        interest_status=interest_status,
        follow_up_status=follow_up_status,
        channel=channel,
        employee=employee,
        search=search,
    )

    return Response(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
