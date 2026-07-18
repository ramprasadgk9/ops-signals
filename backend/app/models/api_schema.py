from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SignalOut(BaseModel):
    id: str
    signal_type: str
    analyzer_id: str | None
    metric_name: str
    service: str | None
    severity: str | None
    confidence: float | None
    importance_score: float
    start_time: datetime | None
    end_time: datetime | None
    summary: str | None
    evidence: dict = Field(default_factory=dict)
    analysis_run_id: str | None


class AnalysisRunOut(BaseModel):
    id: str
    source_type: str
    file_name: str | None = None
    provider: str
    service: str
    metric_name: str
    start_time: datetime
    end_time: datetime
    sample_count: int
    status: str
    created_at: datetime


class CapabilityOut(BaseModel):
    id: str
    analyzer_id: str
    title: str
    description: str
    enabled: bool
    metadata_json: dict


class ServiceMetricOut(BaseModel):
    service: str
    metrics: list[str]


class CsvRunOut(BaseModel):
    analysis_run_id: str
    file_name: str | None = None
    provider: str
    source_type: str
    service: str
    metric_name: str
    sample_count: int
    findings_count: int


class ValidationFindingOut(BaseModel):
    metric_name: str
    service: str | None = None
    title: str
    summary: str
    category: str
    health_status: str
    importance_score: float
    investigation_priority: int
    signal_ids: list[str]
    comparison_json: dict = Field(default_factory=dict)


class ValidationSignalOut(BaseModel):
    signal_id: str
    signal_type: str
    analyzer_id: str
    metric_name: str
    service: str | None = None
    severity: str
    confidence: float
    start_time: datetime
    end_time: datetime
    summary: str
    evidence: dict = Field(default_factory=dict)


class CsvValidationOut(BaseModel):
    provider: str
    source_type: str
    analyzer_id: str
    service: str
    metric_name: str
    sample_count: int
    normalized_preview: list[dict]
    signals: list[ValidationSignalOut]
    findings: list[ValidationFindingOut]


class FindingOut(BaseModel):
    id: int | None = None
    service: str | None
    metric_name: str
    title: str
    summary: str
    category: str
    health_status: str
    importance_score: float
    investigation_priority: int
    signal_ids: list[str]
    comparison_json: dict = Field(default_factory=dict)
    analysis_run_id: str | None = None
    created_at: datetime | None = None


class CaseCreateResponse(BaseModel):
    case_id: int
    finding_id: int
    case_status: str
    memory_status: str


class CaseOut(BaseModel):
    id: int
    finding_id: int
    analysis_run_id: str
    case_title: str
    case_status: str
    finding_snapshot: dict
    investigation_status: str
    investigation_notes: list[dict] = Field(default_factory=list)
    root_cause_status: str
    root_cause_summary: str | None = None
    root_cause_confidence: float | None = None
    root_cause_verified: bool
    corrective_action: str | None = None
    outcome_status: str
    outcome_summary: str | None = None
    memory_status: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class InvestigationUpdateRequest(BaseModel):
    investigation_status: str
    investigation_note: str | None = None


class RCAUpdateRequest(BaseModel):
    root_cause_status: str
    root_cause_summary: str | None = None
    root_cause_confidence: float | None = None
    root_cause_verified: bool = False


class ResolutionUpdateRequest(BaseModel):
    outcome_status: str
    outcome_summary: str | None = None
    corrective_action: str | None = None
