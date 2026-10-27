from __future__ import annotations

from datetime import datetime

from typing import Literal, get_args

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
    # "auto" unless the upload named one; `interval` is what was actually used per series.
    requested_interval: str = "auto"
    interval: str = ""
    warnings: list[str] = Field(default_factory=list)


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
    # Plain-words wording for the card (services/finding_plain.py); None when there isn't enough evidence.
    plain: dict | None = None


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
    requested_interval: str = "auto"
    interval: str = ""
    warnings: list[str] = Field(default_factory=list)
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
    # Prometheus connection (Mimir tenant) its run queried; None for CSV, OTLP and older runs.
    connection_id: str | None = None
    # Where its data came from: "prometheus", "otlp" or "csv"; None when its run isn't known.
    source: str | None = None
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
    # When the problem happened, and whether it was still going on at the end of the analyzed data.
    event_start: datetime | None = None
    event_end: datetime | None = None
    ongoing: bool | None = None
    # The first finding of the same problem; None when this finding is the first.
    problem_id: int | None = None
    # Deploys and other change events near the finding's change (services/finding_changes.py).
    changes: dict | None = None
    # How much to trust it: group, needs-attention tier, tested numbers, the team's own answers
    # (services/finding_trust.py).
    trust: dict | None = None
    # Plain-words wording for the card: badge, headline, what changed, why it matters, what to
    # check, related findings (services/finding_plain.py). None when there isn't enough evidence;
    # title and summary are unchanged either way.
    plain: dict | None = None
    # Per-service analyzer settings it was made with (services/finding_settings.py): each changed
    # setting in words with the value used and the default, and the overrides that set them, with
    # their file and reason. None for a finding made with the default settings.
    custom_settings: dict | None = None


class FindingFeedbackIn(BaseModel):
    verdict: Literal["real_problem", "expected_change", "not_a_problem"]


class FindingAIWordingOut(BaseModel):
    """AI-written lines for a finding's details (backend/app/services/finding_ai_wording.py). A None
    line keeps the template. available is False when there is nothing to show, and reason says why:
    ai_off (no AI provider), no_plain (the finding has no plain wording) or failed (the call failed)."""

    available: bool
    reason: Literal["ai_off", "no_plain", "failed"] | None = None
    why: str | None = None
    check_extra: str | None = None
    related_extra: str | None = None
    model: str | None = None


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
    # The Grafana user who opened it; None when it wasn't opened through Grafana.
    created_by: str | None = None
    # The Grafana user who closed it (resolved, mitigated...); None otherwise.
    resolved_by: str | None = None


# Every value a client sends today: the web UI, the Grafana plugin, MCP, imports and Jira sync.
# Any string used to be stored ("banana"), and a confidence of 7 or -1 too.
InvestigationStatus = Literal["not_started", "in_progress", "on_hold", "completed"]
RootCauseStatus = Literal["unknown", "investigating", "hypothesis", "identified", "confirmed", "ruled_out"]
OutcomeStatus = Literal["pending", "in_progress", "escalated", "mitigated", "resolved", "won_t_fix"]
INVESTIGATION_STATUSES = get_args(InvestigationStatus)
ROOT_CAUSE_STATUSES = get_args(RootCauseStatus)
OUTCOME_STATUSES = get_args(OutcomeStatus)


class InvestigationUpdateRequest(BaseModel):
    investigation_status: InvestigationStatus
    investigation_note: str | None = None


class RCAUpdateRequest(BaseModel):
    root_cause_status: RootCauseStatus
    root_cause_summary: str | None = None
    root_cause_confidence: float | None = Field(default=None, ge=0, le=1)
    root_cause_verified: bool = False


class ResolutionUpdateRequest(BaseModel):
    outcome_status: OutcomeStatus
    outcome_summary: str | None = None
    corrective_action: str | None = None
    learning_outcome_status: Literal["confirmed", "partially_confirmed", "rejected", "inconclusive"] | None = None
    root_cause_category: str | None = None
    resolution_summary: str | None = None
    resolved_by: str | None = None


class CaseDraftSource(BaseModel):
    """One fact a draft was written from, shown under the box so the person can check it."""

    kind: Literal["finding", "deploy", "ticket", "note", "ticket_comment", "similar_case", "root_cause", "corrective_action"]
    label: str
    detail: str | None = None


DraftReasonCode = Literal["ai_off", "not_enough", "failed"]


class RCADraftOut(BaseModel):
    """A suggested-only draft; never written to the case. Use PATCH /rca to actually save one."""

    available: bool
    draft: str | None = None
    based_on_similar_cases: list[int] = Field(default_factory=list)
    sources: list[CaseDraftSource] = Field(default_factory=list)
    reason: str | None = None
    reason_code: DraftReasonCode | None = None


class ResolutionDraftOut(BaseModel):
    """A suggested-only draft reformatting of the case's own notes; never written to the case.
    Use PATCH /resolution to actually save one. `draft` is the outcome summary."""

    available: bool
    draft: str | None = None
    corrective_action: str | None = None
    sources: list[CaseDraftSource] = Field(default_factory=list)
    reason: str | None = None
    reason_code: DraftReasonCode | None = None


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
