from typing import Annotated, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import get_current_active_user
from app.models.user import User
from app.repositories.report_repository import ReportRepository
from app.repositories.batch_repository import BatchRepository
from app.schemas.outreach import (
    ImportCommitRequest,
    ImportCommitResponse,
    ImportPreviewResponse,
    ReportCreateRequest,
    ReportListResponse,
    ReportResponse,
    ReportUpdateRequest,
)
from app.services.outreach_service import OutreachImportService

router = APIRouter(prefix="/api/v1/reports", tags=["Outreach Reports"])

report_repo = ReportRepository()
batch_repo = BatchRepository()
import_service = OutreachImportService()


@router.get("", response_model=ReportListResponse)
def list_reports(
    current_user: Annotated[User, Depends(get_current_active_user)],
    search: Optional[str] = Query(None, description="Search by report title"),
    is_archived: bool = Query(False, description="Filter archived reports"),
    sort_by: str = Query("updated_at", description="Sort by title, created_at, updated_at, total_leads"),
    sort_order: int = Query(-1, description="1 for ASC, -1 for DESC"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    workspace_id = current_user.workspace_id
    skip = (page - 1) * limit
    reports = report_repo.list_reports(
        workspace_id=workspace_id,
        search=search,
        is_archived=is_archived,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    total = report_repo.count_reports(
        workspace_id=workspace_id,
        search=search,
        is_archived=is_archived,
    )
    return ReportListResponse(items=reports, total=total, page=page, limit=limit)


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    report = report_repo.create_report(
        workspace_id=workspace_id,
        title=payload.title,
        description=payload.description,
        created_by=str(current_user.id),
    )
    return report


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )
    return report


@router.patch("/{report_id}", response_model=ReportResponse)
def update_report(
    report_id: str,
    payload: ReportUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )

    updates = {}
    if payload.title is not None:
        updates["title"] = payload.title.strip()
    if payload.description is not None:
        updates["description"] = payload.description.strip()
    if payload.is_archived is not None:
        updates["is_archived"] = payload.is_archived

    updated = report_repo.update_report(workspace_id, report_id, updates)
    return updated


@router.delete("/{report_id}")
def delete_report(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    success = report_repo.delete_report(workspace_id, report_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )
    return {"message": "Report deleted successfully.", "report_id": report_id}


@router.post("/preview", response_model=ImportPreviewResponse)
async def preview_spreadsheet_import(
    current_user: Annotated[User, Depends(get_current_active_user)],
    file: UploadFile = File(...),
    target_report_id: Optional[str] = Form(None),
):
    workspace_id = current_user.workspace_id
    content = await file.read()
    try:
        preview = import_service.preview_import(
            workspace_id=workspace_id,
            filename=file.filename or "upload.csv",
            content=content,
            target_report_id=target_report_id,
            created_by=str(current_user.id),
        )
        return preview
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.post("/commit", response_model=ImportCommitResponse)
def commit_spreadsheet_import(
    payload: ImportCommitRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    try:
        result = import_service.commit_import(
            workspace_id=workspace_id,
            batch_id=payload.batch_id,
            title=payload.title,
            description=payload.description or "",
            target_report_id=payload.target_report_id,
            created_by=str(current_user.id),
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get("/{report_id}/batches")
def get_report_import_batches(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )
    batches = batch_repo.list_batches(workspace_id, report_id)
    return {"items": batches, "total": len(batches)}


@router.post("/{report_id}/recalculate")
def recalculate_report_metrics(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )
    metrics = report_repo.recalculate_metrics(workspace_id, report_id)
    return {"report_id": report_id, "metrics": metrics}
