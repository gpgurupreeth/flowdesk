from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.outreach import (
    LeadFollowUpUpdateRequest,
    LeadListResponse,
    LeadOutcomeUpdateRequest,
    LeadResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Leads & Outreach Prospects"])

lead_repo = LeadRepository()
report_repo = ReportRepository()


@router.get("/reports/{report_id}/leads", response_model=LeadListResponse)
def list_report_leads(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    contact_status: Optional[str] = Query(None),
    interest_status: Optional[str] = Query(None),
    follow_up_status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    employee: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: int = Query(-1),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    workspace_id = current_user.workspace_id
    report = report_repo.get_report(workspace_id, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outreach Report not found.",
        )

    skip = (page - 1) * limit
    leads = lead_repo.find_leads(
        workspace_id=workspace_id,
        report_id=report_id,
        contact_status=contact_status,
        interest_status=interest_status,
        follow_up_status=follow_up_status,
        channel=channel,
        employee=employee,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    total = lead_repo.count_leads(
        workspace_id=workspace_id,
        report_id=report_id,
        contact_status=contact_status,
        interest_status=interest_status,
        follow_up_status=follow_up_status,
        channel=channel,
        employee=employee,
        search=search,
    )
    return LeadListResponse(items=leads, total=total, page=page, limit=limit)


@router.get("/leads", response_model=LeadListResponse)
def list_all_workspace_leads(
    current_user: Annotated[User, Depends(get_current_active_user)],
    contact_status: Optional[str] = Query(None),
    interest_status: Optional[str] = Query(None),
    follow_up_status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    employee: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: int = Query(-1),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    workspace_id = current_user.workspace_id
    skip = (page - 1) * limit
    leads = lead_repo.find_leads(
        workspace_id=workspace_id,
        report_id=None,
        contact_status=contact_status,
        interest_status=interest_status,
        follow_up_status=follow_up_status,
        channel=channel,
        employee=employee,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    total = lead_repo.count_leads(
        workspace_id=workspace_id,
        report_id=None,
        contact_status=contact_status,
        interest_status=interest_status,
        follow_up_status=follow_up_status,
        channel=channel,
        employee=employee,
        search=search,
    )
    return LeadListResponse(items=leads, total=total, page=page, limit=limit)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead_details(
    lead_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )
    return lead


@router.patch("/leads/{lead_id}/outcome", response_model=LeadResponse)
def update_lead_outcome(
    lead_id: str,
    payload: LeadOutcomeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )

    updates = {}
    current_outcome = dict(lead.get("outcome") or {})
    if payload.contact_status:
        current_outcome["contact_status"] = payload.contact_status.strip().lower()
    if payload.interest_status:
        current_outcome["interest_status"] = payload.interest_status.strip().lower()
    current_outcome["source"] = "manual_update"
    updates["outcome"] = current_outcome

    updated = lead_repo.update_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        updates=updates,
        actor_id=str(current_user.id),
    )
    # Recalculate metrics for parent report
    report_id = lead.get("report_id")
    if report_id:
        report_repo.recalculate_metrics(workspace_id, report_id)

    return updated


@router.patch("/leads/{lead_id}/follow-up", response_model=LeadResponse)
def update_lead_follow_up(
    lead_id: str,
    payload: LeadFollowUpUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )

    current_fu = dict(lead.get("follow_up") or {})
    if payload.status:
        current_fu["status"] = payload.status.strip().lower()
    if payload.due_date is not None:
        current_fu["due_date"] = payload.due_date
    if payload.notes is not None:
        current_fu["notes"] = payload.notes
    if payload.assigned_to is not None:
        current_fu["assigned_to"] = payload.assigned_to

    updated = lead_repo.update_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        updates={"follow_up": current_fu},
        actor_id=str(current_user.id),
    )
    # Recalculate metrics for parent report
    report_id = lead.get("report_id")
    if report_id:
        report_repo.recalculate_metrics(workspace_id, report_id)

    return updated


@router.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )
    report_id = lead.get("report_id")
    success = lead_repo.delete_lead(workspace_id, lead_id)
    if success and report_id:
        report_repo.recalculate_metrics(workspace_id, report_id)

    return {"message": "Lead deleted successfully.", "lead_id": lead_id}
