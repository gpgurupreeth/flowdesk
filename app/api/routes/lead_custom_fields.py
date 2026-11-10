
from typing import Annotated
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, get_current_active_user
from app.models.custom_field import CustomFieldDefinition
from app.models.lead import Lead
from app.models.lead_custom_field_value import LeadCustomFieldValue
from app.models.user import User
from app.schemas.custom_field import CustomFieldValueUpdate

router = APIRouter(
    prefix="/api/leads",
    tags=["Lead Custom Fields"],
)


class LeadCustomFieldValueResponse(BaseModel):
    custom_field_id: int
    name: str
    field_type: str
    value: str | None


def _get_owned_lead(
    db: Session,
    lead_id: int,
    current_user: User,
) -> Lead:
    """Fetch a lead, verifying it belongs to the current user."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return lead


@router.get(
    "/{lead_id}/custom-fields",
    response_model=list[LeadCustomFieldValueResponse],
)
def get_lead_custom_fields(
    lead_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    _get_owned_lead(db, lead_id, current_user)

    statement = (
        select(CustomFieldDefinition, LeadCustomFieldValue)
        .outerjoin(
            LeadCustomFieldValue,
            (
                LeadCustomFieldValue.custom_field_id
                == CustomFieldDefinition.id
            )
            & (LeadCustomFieldValue.lead_id == lead_id),
        )
        .where(CustomFieldDefinition.user_id == current_user.id)
        .where(CustomFieldDefinition.is_active.is_(True))
        .order_by(CustomFieldDefinition.name.asc())
    )

    results = db.execute(statement).all()

    return [
        {
            "custom_field_id": definition.id,
            "name": definition.name,
            "field_type": definition.field_type,
            "value": stored_value.value if stored_value else None,
        }
        for definition, stored_value in results
    ]


@router.put(
    "/{lead_id}/custom-fields/{custom_field_id}",
    response_model=LeadCustomFieldValueResponse,
)
def update_lead_custom_field(
    lead_id: int,
    custom_field_id: int,
    payload: CustomFieldValueUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    _get_owned_lead(db, lead_id, current_user)

    definition = db.get(CustomFieldDefinition, custom_field_id)
    if (
        not definition
        or not definition.is_active
        or definition.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Active custom field not found.",
        )

    value = payload.value

    if value is not None:
        value = value.strip()

    if value == "":
        value = None

    if value is not None:
        try:
            if definition.field_type == "number":
                float(value)
            elif definition.field_type == "date":
                date.fromisoformat(value)
            elif definition.field_type == "checkbox":
                if value.casefold() not in {"true", "false"}:
                    raise ValueError("Expected true or false.")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid value for field type '{definition.field_type}'.",
            ) from exc

    statement = select(LeadCustomFieldValue).where(
        LeadCustomFieldValue.lead_id == lead_id,
        LeadCustomFieldValue.custom_field_id == custom_field_id,
    )
    stored_value = db.scalar(statement)

    try:
        if value is None:
            if stored_value:
                db.delete(stored_value)
        elif stored_value:
            stored_value.value = value
        else:
            stored_value = LeadCustomFieldValue(
                lead_id=lead_id,
                custom_field_id=custom_field_id,
                value=value,
            )
            db.add(stored_value)

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "custom_field_id": definition.id,
        "name": definition.name,
        "field_type": definition.field_type,
        "value": value,
    }
