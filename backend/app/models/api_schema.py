from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class SignalOut(BaseModel):
    id: str
    signal_type: str
    analyzer_id: str | None
    metric_name: str
    service: str | None
    cluster: str | None = None
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
    router_version: str | None = None
    feature_extractor_version: str | None = None
    analyzer_registry_version: str | None = None
    series_profile_json: dict | None = None
    router_decisions_json: list[dict] | None = None
    executed_analyzers_json: list[dict] | None = None
    generated_findings_json: list[dict] | None = None
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


class PrometheusMetricSample(BaseModel):
    timestamp: datetime
    value: float
    metric_name: str
    service: str
    labels: dict[str, str] = Field(default_factory=dict)
    series_id: str | None = None


class PrometheusAnalysisRequest(BaseModel):
    provider: str = "prometheus"
    datasource_uid: str
    datasource_name: str | None = None
    service: str
    metric_name: str
    promql: str
    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    step_seconds: int
    samples: list[PrometheusMetricSample]
    series_count: int
    sample_count: int
    max_series: int | None = None
    max_samples_per_series: int | None = None
    warnings: list[str] = Field(default_factory=list)


class PrometheusRunOut(BaseModel):
    analysis_run_id: str
    provider: str
    source_type: str
    datasource_uid: str
    datasource_name: str | None = None
    service: str
    metric_name: str
    promql: str
    from_time: datetime
    to_time: datetime
    step_seconds: int
    sample_count: int
    series_count: int
    findings_count: int
    signal_count: int
    behavior_findings_count: int
    warnings: list[str] = Field(default_factory=list)
    analyzer_selection_mode: str = "all"
    analyzer_routing: list[dict] = Field(default_factory=list)
    executed_analyzers: list[str] = Field(default_factory=list)
    analyzer_executions: list[dict] = Field(default_factory=list)


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
    analyzer_selection_mode: str = "all"
    analyzer_routing: list[dict] = Field(default_factory=list)
    executed_analyzers: list[str] = Field(default_factory=list)
    analyzer_executions: list[dict] = Field(default_factory=list)


class FindingOut(BaseModel):
    id: int | None = None
    service: str | None
    metric_name: str
    # External cluster label the finding's series came from; None for single-cluster data.
    cluster: str | None = None
    title: str
    summary: str
    ai_summary: str | None = None
    category: str
    health_status: str
    importance_score: float
    investigation_priority: int
    signal_ids: list[str]
    comparison_json: dict = Field(default_factory=dict)
    analysis_run_id: str | None = None
    created_at: datetime | None = None
    # Deploys and other change events near the finding's change (services/finding_changes.py).
    changes: dict | None = None


class CaseCreateResponse(BaseModel):
    case_id: int
    finding_id: int | None = None
    behavior_finding_id: int | None = None
    case_status: str
    memory_status: str


class CaseOut(BaseModel):
    id: int
    finding_id: int | None = None
    behavior_finding_id: int | None = None
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
    source: str = "detected"
    source_id: str | None = None
    source_url: str | None = None
    import_batch_id: str | None = None


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
    learning_outcome_status: Literal["confirmed", "partially_confirmed", "rejected", "inconclusive"] | None = None
    root_cause_category: str | None = None
    resolution_summary: str | None = None
    resolved_by: str | None = None


class RCADraftOut(BaseModel):
    """A suggested-only draft; never written to the case. Use PATCH /rca to actually save one."""

    available: bool
    draft: str | None = None
    based_on_similar_cases: list[int] = Field(default_factory=list)
    reason: str | None = None


class ResolutionDraftOut(BaseModel):
    """A suggested-only draft reformatting of the case's own notes; never written to the case.
    Use PATCH /resolution to actually save one."""

    available: bool
    draft: str | None = None
    reason: str | None = None


class LearningOutcomeCreateRequest(BaseModel):
    outcome_status: Literal["confirmed", "partially_confirmed", "rejected", "inconclusive"]
    outcome_summary: str | None = None
    root_cause_category: str | None = None
    resolution_summary: str | None = None
    resolved_by: str | None = None


class AnalyzerLearningOutcomeOut(BaseModel):
    id: str
    organization_id: str | None = None
    service_id: str | None = None
    metric_name: str
    analysis_run_id: str
    finding_id: int | None = None
    case_id: int
    router_version: str | None = None
    feature_extractor_version: str | None = None
    analyzer_registry_version: str | None = None
    series_profile: dict
    router_decisions: list[dict]
    executed_analyzers: list[dict]
    generated_findings: list[dict] | None = None
    outcome_status: str
    outcome_summary: str | None = None
    root_cause_category: str | None = None
    resolution_summary: str | None = None
    confirmed_analyzers: list[str] = Field(default_factory=list)
    rejected_analyzers: list[str] = Field(default_factory=list)
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
