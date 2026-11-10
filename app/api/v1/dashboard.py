from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.outreach import WorkspaceDashboardResponse

router = APIRouter(prefix="/api/v1", tags=["Dashboard & Outreach Analytics"])

lead_repo = LeadRepository()
report_repo = ReportRepository()


@router.get("/dashboard", response_model=WorkspaceDashboardResponse)
def get_workspace_dashboard(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    workspace_id = current_user.workspace_id
    metrics = lead_repo.get_workspace_metrics(workspace_id)
    return metrics


@router.get("/reports/{report_id}/dashboard")
def get_report_dashboard(
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

    leads_col = lead_repo.collection
    match_query = {"workspace_id": workspace_id, "report_id": report_id}

    # Pipeline for Channel distribution
    channel_pipeline = [
        {"$match": match_query},
        {"$group": {"_id": "$channel", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    channel_distribution = {
        doc["_id"] or "unknown": doc["count"]
        for doc in leads_col.aggregate(channel_pipeline)
    }

    # Pipeline for Employee distribution
    employee_pipeline = [
        {"$match": {**match_query, "assigned_employee": {"$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$assigned_employee", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    employee_distribution = {
        doc["_id"]: doc["count"]
        for doc in leads_col.aggregate(employee_pipeline)
    }

    # Interest Status distribution
    interest_pipeline = [
        {"$match": match_query},
        {"$group": {"_id": "$outcome.interest_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    interest_distribution = {
        doc["_id"] or "unknown": doc["count"]
        for doc in leads_col.aggregate(interest_pipeline)
    }

    # Contact Status distribution
    contact_pipeline = [
        {"$match": match_query},
        {"$group": {"_id": "$outcome.contact_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    contact_distribution = {
        doc["_id"] or "not_contacted": doc["count"]
        for doc in leads_col.aggregate(contact_pipeline)
    }

    return {
        "report": report,
        "metrics": report.get("metrics", {}),
        "channel_distribution": channel_distribution,
        "employee_distribution": employee_distribution,
        "interest_distribution": interest_distribution,
        "contact_distribution": contact_distribution,
    }
