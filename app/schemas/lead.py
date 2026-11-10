
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LeadCustomFieldItem(BaseModel):
    custom_field_id: int
    name: str
    field_type: str
    value: str | None


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    company: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=150)
    status: str | None = Field(default="New", max_length=30)
    deal_value: float | None = Field(default=None, ge=0)
    follow_up_date: date | None = None


class LeadUpdate(BaseModel):
    """Fields that can be updated on an existing lead."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    company: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=150)
    status: str | None = Field(default=None, max_length=30)
    deal_value: float | None = Field(default=None, ge=0)
    follow_up_date: date | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    email: EmailStr
    company: str
    phone: str | None
    location: str | None
    status: str
    deal_value: float | None
    follow_up_date: date | None
    created_at: datetime
    updated_at: datetime
    imported_at: datetime | None = None
    custom_fields: list[LeadCustomFieldItem] = []
