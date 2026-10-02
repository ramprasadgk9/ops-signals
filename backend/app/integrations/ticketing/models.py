from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class TicketDraft(BaseModel):
    """Case snapshot prepared for outbound ticket creation."""
    case_id: int
    case_title: str
    summary: str
    service: str
    metric_name: str
    health_status: str
    importance_score: float
    analysis_run_id: str
    rca_summary: str | None = None
    outcome_summary: str | None = None
    deep_link_url: str | None = None
    raw_findings: list[dict] = Field(default_factory=list)


class TicketCreationResult(BaseModel):
    """Result returned by a provider upon issue creation or reconciliation."""
    remote_id: str
    display_key: str
    ticket_url: str
    initial_status: str = "open"


class RemoteTicketSnapshot(BaseModel):
    """Result returned by a polling sync of remote ticket state."""
    remote_id: str
    display_key: str
    remote_status: str
    comments: list[dict] = Field(default_factory=list)
    changelog_items: list[dict] = Field(default_factory=list)
    cursor: str | None = None


class RemoteEventDraft(BaseModel):
    """Normalized remote event from polling sync or inbound webhook."""
    remote_id: str
    display_key: str
    remote_event_id: str
    event_type: str
    summary: str
    author: str | None = None
    observed_remote_status: str | None = None
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime


class TicketView(BaseModel):
    """Read-only active ticket link representation."""
    case_id: int
    provider: str
    remote_id: str
    display_key: str
    ticket_url: str
    observed_remote_status: str | None = None
    last_synced_at: datetime | None = None
    sync_status: str = "synced"


class TicketOperationView(BaseModel):
    """Status view of an asynchronous outbox operation."""
    operation_id: str
    case_id: int
    provider: str
    operation_type: str
    status: str
    attempts: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class TicketEventView(BaseModel):
    """Immutable external activity timeline entry."""
    id: int
    case_id: int
    provider: str
    remote_event_id: str
    event_type: str
    author: str | None = None
    summary: str
    occurred_at: datetime
    created_at: datetime
    promoted_to_note: bool = False
    auto_promoted: bool = False


class CaseNotePromoteResult(BaseModel):
    """Result of promoting an external ticket event into an investigation note."""
    success: bool
    case_id: int
    event_id: int
    note: str
    investigation_status: str
    already_promoted: bool = False
    auto_promoted: bool = False


class CommentTriageResult(BaseModel):
    """Result of evaluating unpromoted ticket comments for automated promotion."""
    case_id: int
    evaluated_count: int
    promoted_count: int
    promoted_notes: list[str] = Field(default_factory=list)


class AmbiguousResolutionRequest(BaseModel):
    """Operator action payload for resolving ambiguous outcome operations."""
    action: str  # 'check_again' | 'link_existing' | 'force_create_new'
    remote_key: str | None = None
