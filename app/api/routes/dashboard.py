
"""Overview dashboard API - real metrics from PostgreSQL."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, get_current_active_user
from app.models.lead import Lead
from app.models.user import User

router = APIRouter(prefix="/api/dashboard", tags=["Overview"])

# Valid pipeline stages
PIPELINE_STAGES = ["New", "Contacted", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]


@router.get("/overview")
def get_overview(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
    days: int = Query(default=30, ge=1, le=365, description="Date range in days for trend"),
):
    """Get overview dashboard metrics for the authenticated user.

    All metrics are computed from PostgreSQL data owned by the current user.
    """
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # --- KPI counts ---
    total_leads = db.query(Lead).filter(Lead.user_id == current_user.id).count()

    stage_counts = {}
    for stage in PIPELINE_STAGES:
        count = (
            db.query(Lead)
            .filter(Lead.user_id == current_user.id)
            .filter(Lead.status == stage)
            .count()
        )
        stage_counts[stage] = count

    new_leads = stage_counts.get("New", 0)
    qualified_leads = stage_counts.get("Qualified", 0)
    won_deals = stage_counts.get("Won", 0)

    # Conversion rate: Won / (Won + Lost)
    closed = stage_counts.get("Won", 0) + stage_counts.get("Lost", 0)
    conversion_rate = round((won_deals / closed * 100), 1) if closed > 0 else 0.0

    # Follow-up metrics
    today = date.today()
    followups_due_today = (
        db.query(Lead)
        .filter(Lead.user_id == current_user.id)
        .filter(Lead.follow_up_date == today)
        .count()
    )

    overdue_followups = (
        db.query(Lead)
        .filter(Lead.user_id == current_user.id)
        .filter(Lead.follow_up_date < today)
        .filter(Lead.status.notin_(["Won", "Lost"]))
        .count()
    )

    upcoming_followups = (
        db.query(Lead)
        .filter(Lead.user_id == current_user.id)
        .filter(Lead.follow_up_date > today)
        .filter(Lead.status.notin_(["Won", "Lost"]))
        .count()
    )

    if total_leads == 0:
        from app.repositories.lead_repository import LeadRepository
        lead_repo = LeadRepository()
        m = lead_repo.get_workspace_metrics(current_user.workspace_id)
        if m["total_leads"] > 0:
            total_leads = m["total_leads"]
            new_leads = m["total_not_contacted"]
            qualified_leads = m["total_potentially_interested"]
            won_deals = m["total_interested"]
            closed = won_deals + m["total_not_interested"]
            conversion_rate = round((won_deals / closed * 100), 1) if closed > 0 else 0.0
            followups_due_today = m["follow_ups_due"]
            overdue_followups = m["follow_ups_overdue"]
            stage_counts = {
                "New": new_leads,
                "Contacted": m["total_contacted"],
                "Qualified": qualified_leads,
                "Proposal": 0,
                "Negotiation": 0,
                "Won": won_deals,
                "Lost": m["total_not_interested"],
            }

    # --- Lead creation trend (daily) ---
    trend_rows = (
        db.query(
            func.date(Lead.created_at).label("day"),
            func.count(Lead.id).label("count"),
        )
        .filter(Lead.user_id == current_user.id)
        .filter(Lead.created_at >= start_date)
        .group_by(func.date(Lead.created_at))
        .order_by(func.date(Lead.created_at))
        .all()
    )

    # Build a complete series with zero-filled days
    trend_by_day = {str(row.day): row.count for row in trend_rows}
    trend_series = []
    for i in range(days + 1):
        day = (now - timedelta(days=days - i)).date()
        trend_series.append({
            "date": day.isoformat(),
            "count": trend_by_day.get(day.isoformat(), 0),
        })

    # --- Recent leads (last 10) ---
    recent_leads = (
        db.query(Lead)
        .filter(Lead.user_id == current_user.id)
        .order_by(Lead.created_at.desc())
        .limit(10)
        .all()
    )

    recent_lead_list = []
    for lead in recent_leads:
        recent_lead_list.append({
            "id": lead.id,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        })

    return {
        "kpi": {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "won_deals": won_deals,
            "conversion_rate": conversion_rate,
            "followups_due_today": followups_due_today,
            "overdue_followups": overdue_followups,
            "upcoming_followups": upcoming_followups,
        },
        "status_distribution": stage_counts,
        "lead_trend": trend_series,
        "recent_leads": recent_lead_list,
        "period_days": days,
    }
