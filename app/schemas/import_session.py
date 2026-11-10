
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportPlanRequest(BaseModel):
    """Client-submitted mapping and custom-field configuration (Stage B)."""

    session_key: str
    filename: str = ""
    mapping: dict[str, str | None] = Field(default_factory=dict)
    custom_fields: dict[str, dict[str, str]] = Field(default_factory=dict)


class ImportPlanRow(BaseModel):
    """A single validated and matched import row."""

    row_number: int
    action: str  # create | update | review | skip
    existing_lead_id: int | None = None
    lead: dict[str, Any]
    custom_values: dict[str, Any]
    review_reasons: list[str] = Field(default_factory=list)
    preserve_existing_fields: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ImportPlanResponse(BaseModel):
    """Server-computed import plan (Stages C-F). Returned before commit."""

    model_config = ConfigDict(from_attributes=True)

    session_key: str
    filename: str
    total_rows: int
    summary: dict[str, int]
    rows: list[ImportPlanRow]
    expires_at: datetime


class ImportCommitRequest(BaseModel):
    """Client confirmation of an import session (Stage G)."""

    session_key: str


class ImportCommitResponse(BaseModel):
    """Import result summary returned after a successful commit."""

    session_key: str
    status: str
    created: int
    updated: int
    reviewed: int
    skipped: int
    errors: int
    leads: list[dict[str, Any]]
    custom_fields_created: int
    custom_values_saved: int


class ImportSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_key: str
    filename: str
    status: str
    created_at: datetime
    expires_at: datetime
    committed_at: datetime | None = None
