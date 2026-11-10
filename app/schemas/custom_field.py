
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CustomFieldType = Literal["text", "number", "date", "checkbox"]


class CustomFieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    field_type: CustomFieldType = "text"


class CustomFieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    field_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomFieldValueUpdate(BaseModel):
    value: str | None = None
