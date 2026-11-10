from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)


class ReportUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    is_archived: Optional[bool] = None


class ReportMetrics(BaseModel):
    total: int = 0
    contacted: int = 0
    not_contacted: int = 0
    interested: int = 0
    potentially_interested: int = 0
    not_interested: int = 0
    awaiting_response: int = 0
    unclear: int = 0
    follow_up_due: int = 0
    follow_up_overdue: int = 0


class ReportResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str = ""
    created_by: str = ""
    source_file: Optional[str] = None
    is_archived: bool = False
    total_leads: int = 0
    metrics: Dict[str, Any] = {}
    created_at: str
    updated_at: str


class ReportListResponse(BaseModel):
    items: List[ReportResponse]
    total: int
    page: int
    limit: int


class NormalizedLead(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    deal_value: Optional[float] = None


class LeadOutcome(BaseModel):
    contact_status: str = "not_contacted"
    interest_status: str = "unknown"
    source: str = "imported"
    original_status: Optional[str] = None
    original_interest: Optional[str] = None


class LeadFollowUp(BaseModel):
    status: str = "not_required"
    due_date: Optional[str] = None
    reason: str = ""
    notes: str = ""
    completed_at: Optional[str] = None
    assigned_to: Optional[str] = None


class LeadResponse(BaseModel):
    id: str
    workspace_id: str
    report_id: str
    attributes: Dict[str, Any] = {}
    normalized: Dict[str, Any] = {}
    outcome: Dict[str, Any] = {}
    channel: str = "unknown"
    assigned_employee: Optional[str] = None
    follow_up: Dict[str, Any] = {}
    timestamps: Dict[str, Any] = {}
    history: List[Dict[str, Any]] = []


class LeadListResponse(BaseModel):
    items: List[LeadResponse]
    total: int
    page: int
    limit: int


class LeadOutcomeUpdateRequest(BaseModel):
    contact_status: Optional[str] = None
    interest_status: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None


class LeadFollowUpUpdateRequest(BaseModel):
    status: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None


class ImportPreviewResponse(BaseModel):
    batch_id: str
    filename: str
    file_size: int
    total_rows: int
    suggested_title: str
    detected_columns: List[Dict[str, Any]]
    sample_rows: List[Dict[str, Any]]
    summary: Dict[str, int]


class ImportCommitRequest(BaseModel):
    batch_id: str
    title: Optional[str] = None
    description: Optional[str] = ""
    target_report_id: Optional[str] = None


class ImportCommitResponse(BaseModel):
    batch_id: str
    report_id: str
    status: str
    summary: Dict[str, Any]
    metrics: Dict[str, Any]


class WorkspaceDashboardResponse(BaseModel):
    total_reports: int
    total_leads: int
    total_contacted: int
    total_not_contacted: int
    total_interested: int
    total_potentially_interested: int
    total_not_interested: int
    total_awaiting_response: int
    follow_ups_due: int
    follow_ups_overdue: int
    recent_reports: List[Dict[str, Any]]


class FollowUpQueueResponse(BaseModel):
    items: List[LeadResponse]
    total: int
    page: int
    limit: int
    category: str
    counts_by_category: Dict[str, int]
