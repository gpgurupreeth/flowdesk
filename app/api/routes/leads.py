
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import DbSession, get_current_active_user
from app.models.custom_field import CustomFieldDefinition
from app.models.lead import Lead
from app.models.lead_custom_field_value import LeadCustomFieldValue
from app.models.user import User
from app.schemas.lead import (
    LeadCreate,
    LeadResponse,
    LeadUpdate,
    LeadCustomFieldItem,
)

router = APIRouter(prefix="/api/leads", tags=["Leads"])

VALID_STATUSES = [
    "New",
    "Contacted",
    "Qualified",
    "Proposal",
    "Negotiation",
    "Won",
    "Lost",
]


def _validate_status(status_value: str | None) -> None:
    """Reject statuses outside the pipeline, so leads never disappear
    from the board because of an unrecognized status value."""
    if status_value is not None and status_value not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid status '{status_value}'. "
                f"Valid statuses: {', '.join(VALID_STATUSES)}."
            ),
        )


@router.post(
    "",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_lead(
    payload: LeadCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    _validate_status(payload.status)
    lead = Lead(
        user_id=current_user.id,
        name=payload.name.strip(),
        email=str(payload.email).strip().lower(),
        company=payload.company.strip(),
        phone=payload.phone,
        location=payload.location,
        status=payload.status or "New",
        deal_value=payload.deal_value,
        follow_up_date=payload.follow_up_date,
    )

    try:
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return LeadResponse.model_validate(lead)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save the lead.",
        )


@router.get("/pipeline")
def get_pipeline(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Get leads grouped by pipeline stage for the Kanban board.

    Returns a dict mapping each stage to a list of leads, plus
    aggregate counts and deal values per stage.
    """
    stages = ["New", "Contacted", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]

    statement = (
        select(Lead)
        .where(Lead.user_id == current_user.id)
        .order_by(Lead.created_at.desc())
    )
    leads = db.scalars(statement).all()

    lead_ids = [lead.id for lead in leads]

    custom_fields_by_lead: dict[int, list[dict]] = {}
    if lead_ids:
        values_statement = (
            select(LeadCustomFieldValue, CustomFieldDefinition)
            .join(
                CustomFieldDefinition,
                LeadCustomFieldValue.custom_field_id == CustomFieldDefinition.id,
            )
            .where(LeadCustomFieldValue.lead_id.in_(lead_ids))
            .where(CustomFieldDefinition.is_active.is_(True))
            .where(CustomFieldDefinition.user_id == current_user.id)
            .order_by(CustomFieldDefinition.name.asc())
        )
        results = db.execute(values_statement).all()
        for value, definition in results:
            custom_fields_by_lead.setdefault(value.lead_id, []).append({
                "custom_field_id": definition.id,
                "name": definition.name,
                "field_type": definition.field_type,
                "value": value.value,
            })

    lead_dicts = []
    for lead in leads:
        lead_dicts.append({
            "id": lead.id,
            "user_id": lead.user_id,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            "phone": lead.phone,
            "location": lead.location,
            "status": lead.status,
            "deal_value": float(lead.deal_value) if lead.deal_value is not None else None,
            "follow_up_date": lead.follow_up_date.isoformat() if lead.follow_up_date else None,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
            "imported_at": lead.imported_at.isoformat() if lead.imported_at else None,
            "custom_fields": custom_fields_by_lead.get(lead.id, []),
        })

    if not lead_dicts:
        from app.repositories.lead_repository import LeadRepository
        mongo_repo = LeadRepository()
        mongo_leads = mongo_repo.find_leads(workspace_id=current_user.workspace_id, limit=500)
        for ml in mongo_leads:
            attrs = ml.get("attributes", {})
            norm = ml.get("normalized", {})
            outcome = ml.get("outcome", {})
            fu = ml.get("follow_up", {})

            st = attrs.get("Original Status") or attrs.get("Lead Status") or attrs.get("Status")
            if st not in stages:
                if outcome.get("interest_status") == "interested":
                    st = "Won"
                elif outcome.get("interest_status") == "not_interested":
                    st = "Lost"
                elif outcome.get("interest_status") == "potentially_interested":
                    st = "Qualified"
                elif outcome.get("contact_status") == "contacted":
                    st = "Contacted"
                else:
                    st = "New"

            lead_dicts.append({
                "id": ml.get("pg_id") or ml["id"],
                "user_id": current_user.id,
                "name": norm.get("name") or "Unnamed",
                "email": norm.get("email") or "",
                "company": norm.get("company") or "—",
                "phone": norm.get("phone"),
                "location": norm.get("location"),
                "status": st,
                "deal_value": norm.get("deal_value"),
                "follow_up_date": fu.get("due_date"),
                "created_at": ml.get("timestamps", {}).get("created_at"),
                "updated_at": ml.get("timestamps", {}).get("updated_at"),
                "imported_at": ml.get("timestamps", {}).get("first_seen_at"),
                "custom_fields": [],
            })

    pipeline = {}
    for stage in stages:
        stage_leads = [l for l in lead_dicts if l["status"] == stage]
        stage_value = sum((l["deal_value"] or 0) for l in stage_leads)
        pipeline[stage] = {
            "leads": stage_leads,
            "count": len(stage_leads),
            "total_value": round(stage_value, 2),
        }

    open_stages = ["New", "Contacted", "Qualified", "Proposal", "Negotiation"]
    open_value = sum(pipeline[s]["total_value"] for s in open_stages)
    won_value = pipeline["Won"]["total_value"]
    lost_value = pipeline["Lost"]["total_value"]

    return {
        "stages": pipeline,
        "summary": {
            "total_leads": len(lead_dicts),
            "open_pipeline_value": round(open_value, 2),
            "won_value": round(won_value, 2),
            "lost_value": round(lost_value, 2),
        },
    }


@router.get("", response_model=list[LeadResponse])
def list_leads(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """List leads owned by the authenticated user."""
    statement = (
        select(Lead)
        .where(Lead.user_id == current_user.id)
        .order_by(Lead.id.desc())
    )
    leads = db.scalars(statement).all()

    if not leads:
        return []

    lead_ids = [lead.id for lead in leads]

    values_statement = (
        select(LeadCustomFieldValue, CustomFieldDefinition)
        .join(
            CustomFieldDefinition,
            LeadCustomFieldValue.custom_field_id == CustomFieldDefinition.id,
        )
        .where(LeadCustomFieldValue.lead_id.in_(lead_ids))
        .where(CustomFieldDefinition.is_active.is_(True))
        .where(CustomFieldDefinition.user_id == current_user.id)
        .order_by(CustomFieldDefinition.name.asc())
    )
    results = db.execute(values_statement).all()

    custom_fields_by_lead: dict[int, list[dict]] = {}
    for value, definition in results:
        custom_fields_by_lead.setdefault(value.lead_id, []).append({
            "custom_field_id": definition.id,
            "name": definition.name,
            "field_type": definition.field_type,
            "value": value.value,
        })

    return [
        LeadResponse(
            id=lead.id,
            user_id=lead.user_id,
            name=lead.name,
            email=lead.email,
            company=lead.company,
            phone=lead.phone,
            location=lead.location,
            status=lead.status,
            deal_value=float(lead.deal_value) if lead.deal_value is not None else None,
            follow_up_date=lead.follow_up_date,
            created_at=lead.created_at,
            updated_at=lead.updated_at,
            imported_at=lead.imported_at,
            custom_fields=custom_fields_by_lead.get(lead.id, []),
        )
        for lead in leads
    ]


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
)
def get_lead(
    lead_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Get a single lead owned by the authenticated user."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")

    values_statement = (
        select(LeadCustomFieldValue, CustomFieldDefinition)
        .join(
            CustomFieldDefinition,
            LeadCustomFieldValue.custom_field_id == CustomFieldDefinition.id,
        )
        .where(LeadCustomFieldValue.lead_id == lead_id)
        .where(CustomFieldDefinition.is_active.is_(True))
        .where(CustomFieldDefinition.user_id == current_user.id)
        .order_by(CustomFieldDefinition.name.asc())
    )
    results = db.execute(values_statement).all()

    custom_fields = [
        {
            "custom_field_id": definition.id,
            "name": definition.name,
            "field_type": definition.field_type,
            "value": value.value,
        }
        for value, definition in results
    ]

    return LeadResponse(
        id=lead.id,
        user_id=lead.user_id,
        name=lead.name,
        email=lead.email,
        company=lead.company,
        phone=lead.phone,
        location=lead.location,
        status=lead.status,
        deal_value=float(lead.deal_value) if lead.deal_value is not None else None,
        follow_up_date=lead.follow_up_date,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        imported_at=lead.imported_at,
        custom_fields=custom_fields,
    )


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Update fields on a lead owned by the authenticated user."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")

    _validate_status(payload.status)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)

    try:
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return LeadResponse.model_validate(lead)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update the lead.",
        )


@router.delete(
    "/{lead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_lead(
    lead_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Delete a lead owned by the authenticated user."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")

    try:
        db.delete(lead)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete the lead.",
        )

    return None
