
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession, get_current_active_user
from app.models.custom_field import CustomFieldDefinition
from app.models.user import User
from app.schemas.custom_field import (
    CustomFieldCreate,
    CustomFieldResponse,
)

router = APIRouter(
    prefix="/api/custom-fields",
    tags=["Custom Fields"],
)

DbSessionUser = Annotated[tuple[Session, User], Depends(lambda db, user: (db, user))]


def _get_db_and_user(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return db, current_user


@router.post(
    "",
    response_model=CustomFieldResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_custom_field(
    field_data: CustomFieldCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    normalized_name = field_data.name.strip()

    if not normalized_name:
        raise HTTPException(
            status_code=422,
            detail="Custom field name cannot be empty.",
        )

    # Check for existing field owned by this user (case-insensitive).
    existing_field = db.scalar(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.user_id == current_user.id,
            func.lower(CustomFieldDefinition.name)
            == normalized_name.casefold(),
        )
    )

    if existing_field:
        if not existing_field.is_active:
            raise HTTPException(
                status_code=409,
                detail="This custom field exists but is inactive.",
            )

        if existing_field.field_type != field_data.field_type:
            raise HTTPException(
                status_code=409,
                detail=(
                    "A field with this name already exists "
                    "with a different type."
                ),
            )

        # Reuse the existing definition instead of creating a duplicate.
        return existing_field

    custom_field = CustomFieldDefinition(
        user_id=current_user.id,
        name=normalized_name,
        field_type=field_data.field_type,
    )

    db.add(custom_field)

    try:
        db.commit()
        db.refresh(custom_field)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A custom field with this name already exists.",
        )

    return custom_field


@router.get("", response_model=list[CustomFieldResponse])
def list_custom_fields(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """List active custom-field definitions owned by the authenticated user."""
    statement = (
        select(CustomFieldDefinition)
        .where(CustomFieldDefinition.user_id == current_user.id)
        .where(CustomFieldDefinition.is_active.is_(True))
        .order_by(CustomFieldDefinition.name.asc())
    )

    return db.scalars(statement).all()
