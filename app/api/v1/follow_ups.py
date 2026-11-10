from datetime import datetime, timezone
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import get_current_active_user
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.outreach import FollowUpQueueResponse, LeadResponse

router = APIRouter(prefix="/api/v1/follow-ups", tags=["Follow-up Intelligence Queue"])

lead_repo = LeadRepository()
report_repo = ReportRepository()


class RescheduleRequest(BaseModel):
    due_date: str
    notes: Optional[str] = None


class FollowUpNoteRequest(BaseModel):
    notes: str


@router.get("", response_model=FollowUpQueueResponse)
def get_follow_up_queue(
    current_user: Annotated[User, Depends(get_current_active_user)],
    category: str = Query("due_today", description="due_today, overdue, suggested, awaiting_response, uncontacted, review_required, completed, all"),
    report_id: Optional[str] = Query(None),
    employee: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    workspace_id = current_user.workspace_id
    skip = (page - 1) * limit

    items = lead_repo.get_follow_up_queue(
        workspace_id=workspace_id,
        category=category,
        report_id=report_id,
        employee=employee,
        channel=channel,
        search=search,
        skip=skip,
        limit=limit,
    )
    total = lead_repo.count_follow_up_queue(
        workspace_id=workspace_id,
        category=category,
        report_id=report_id,
        employee=employee,
        channel=channel,
        search=search,
    )

    # Compute counts for all main categories for the tab badges
    categories = ["due_today", "overdue", "suggested", "awaiting_response", "uncontacted", "review_required", "completed"]
    counts = {}
    for cat in categories:
        counts[cat] = lead_repo.count_follow_up_queue(
            workspace_id=workspace_id,
            category=cat,
            report_id=report_id,
            employee=employee,
            channel=channel,
            search=search,
        )

    return FollowUpQueueResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        category=category,
        counts_by_category=counts,
    )


@router.patch("/{lead_id}/complete", response_model=LeadResponse)
def complete_follow_up(
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

    fu = dict(lead.get("follow_up") or {})
    fu["status"] = "completed"
    fu["completed_at"] = datetime.now(timezone.utc).isoformat()

    updated = lead_repo.update_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        updates={"follow_up": fu},
        actor_id=str(current_user.id),
    )
    report_id = lead.get("report_id")
    if report_id:
        report_repo.recalculate_metrics(workspace_id, report_id)

    return updated


@router.patch("/{lead_id}/reschedule", response_model=LeadResponse)
def reschedule_follow_up(
    lead_id: str,
    payload: RescheduleRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )

    today_str = datetime.now(timezone.utc).date().isoformat()
    fu_status = "scheduled"
    if payload.due_date < today_str:
        fu_status = "overdue"
    elif payload.due_date == today_str:
        fu_status = "due"

    fu = dict(lead.get("follow_up") or {})
    fu["status"] = fu_status
    fu["due_date"] = payload.due_date
    if payload.notes:
        old_notes = fu.get("notes") or ""
        fu["notes"] = f"{old_notes}\n[Rescheduled]: {payload.notes}".strip()

    updated = lead_repo.update_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        updates={"follow_up": fu},
        actor_id=str(current_user.id),
    )
    report_id = lead.get("report_id")
    if report_id:
        report_repo.recalculate_metrics(workspace_id, report_id)

    return updated


@router.post("/{lead_id}/note", response_model=LeadResponse)
def add_follow_up_note(
    lead_id: str,
    payload: FollowUpNoteRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    lead = lead_repo.get_lead_by_id(workspace_id, lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead record not found.",
        )

    fu = dict(lead.get("follow_up") or {})
    old_notes = fu.get("notes") or ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    new_note = f"[{timestamp}]: {payload.notes.strip()}"
    fu["notes"] = f"{old_notes}\n{new_note}".strip() if old_notes else new_note

    updated = lead_repo.update_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        updates={"follow_up": fu},
        actor_id=str(current_user.id),
    )
    return updated
