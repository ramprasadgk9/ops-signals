from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# A bare file name inside config/behavior_definitions.d/ - no directories, so no path traversal.
PACK_FILE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.ya?ml$"


class BehaviorConditionOut(BaseModel):
    fact: str
    operator: str
    value: object
    passed: bool


class BehaviorEvaluationOut(BaseModel):
    definition_id: str
    definition_version: int
    title: str
    description: str
    matched: bool
    confidence: float
    service: str | None = None
    analysis_run_id: str | None = None
    facts: dict = Field(default_factory=dict)
    matched_conditions: list[BehaviorConditionOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    correlation: dict = Field(default_factory=dict)


class BehaviorDefinitionOut(BaseModel):
    id: str
    enabled: bool
    version: int
    title: str
    description: str
    scope: dict = Field(default_factory=dict)
    inputs: list[dict] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)
    correlation: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    source_file: str | None = None


class FactDescriptorOut(BaseModel):
    key: str
    description: str
    example: object


class BehaviorConditionIn(BaseModel):
    fact: str
    operator: str
    value: object


class BehaviorInputIn(BaseModel):
    alias: str
    metric_name: str
    analyzers: list[str] = Field(default_factory=list)


class BehaviorOutputIn(BaseModel):
    category: str = "behavior"
    severity: str = "medium"
    title: str
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class BehaviorDefinitionDraftIn(BaseModel):
    """A not-yet-saved definition, used by /validate and /dry-run — same shape as one entry
    under behavior_definitions: in the YAML, but as JSON so the Behavior Lab can post a draft
    without writing to disk first."""

    id: str
    enabled: bool = True
    version: int = 1
    title: str
    description: str = ""
    scope: dict = Field(default_factory=dict)
    inputs: list[BehaviorInputIn] = Field(default_factory=list)
    conditions: dict[str, list[BehaviorConditionIn]] = Field(default_factory=dict)
    correlation: dict = Field(default_factory=dict)
    output: BehaviorOutputIn


class ValidationResultOut(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DryRunRequest(BaseModel):
    definition: BehaviorDefinitionDraftIn
    analysis_run_id: str
    service: str | None = None


class BehaviorFindingOut(BaseModel):
    id: int
    behavior_id: str
    definition_id: str
    definition_version: int
    title: str
    summary: str
    ai_explanation: str | None = None
    category: str
    severity: str
    service: str | None = None
    analysis_run_id: str | None = None
    input_metrics_json: dict = Field(default_factory=dict)
    facts_json: dict = Field(default_factory=dict)
    evidence_json: list[str] = Field(default_factory=list)
    matched_conditions_json: list[dict] = Field(default_factory=list)
    confidence: float
    correlation_json: dict = Field(default_factory=dict)
    case_id: int | None = None
    occurrence_count: int = 1
    last_seen_at: datetime
    created_at: datetime


class BehaviorPatternSuggestionOut(BaseModel):
    id: int
    service: str | None = None
    metric_a: str
    metric_b: str
    co_occurrence_count: int
    metric_a_occasions: int
    metric_b_occasions: int
    correlation_strength: float
    sample_analysis_run_ids: list[str] = Field(default_factory=list)
    draft_definition_json: dict = Field(default_factory=dict)
    draft_yaml_text: str
    status: str
    created_at: datetime


class PromoteSuggestionRequest(BaseModel):
    pack_file: str = Field(default="suggested_patterns.yml", pattern=PACK_FILE_PATTERN)


class SaveDraftRequest(BaseModel):
    definition: BehaviorDefinitionDraftIn
    pack_file: str = Field(default="custom_patterns.yml", pattern=PACK_FILE_PATTERN)


class SaveDraftResult(BaseModel):
    saved: bool
    pack_file: str
    validation: ValidationResultOut


class CatalogSignalOut(BaseModel):
    alias: str
    label: str
    shape: str
    metric_hint: str
    keywords: list[str] = Field(default_factory=list)
    analyzers: list[str] = Field(default_factory=list)


class CatalogPatternOut(BaseModel):
    """One known pattern (config/behavior_patterns_catalog.yml): a shipped rule with its proof, or
    a template with its signals and a draft definition for the builder."""

    key: str
    rule: str | None = None
    name: str
    area: str | None = None
    meaning: str = ""
    why: str = ""
    check_first: str = ""
    proof: str
    scenarios: list[str] = Field(default_factory=list)
    signals: list[CatalogSignalOut] = Field(default_factory=list)
    draft: dict | None = None


class HistoryPreviewRequest(BaseModel):
    """Try a draft definition on a service's recent analysis runs, as the pipeline would have."""

    definition: BehaviorDefinitionDraftIn
    service: str
    hours: int = Field(default=168, ge=1, le=720)
    max_runs: int = Field(default=50, ge=1, le=200)


class HistoryRunConditionOut(BaseModel):
    group: str
    fact: str
    operator: str
    value: object
    passed: bool
    actual: object = None


class HistoryRunChangeOut(BaseModel):
    alias: str
    signed_change_percent: float | None = None


class HistoryRunOut(BaseModel):
    analysis_run_id: str
    at: datetime | None = None
    matched: bool
    missing_inputs: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    conditions: list[HistoryRunConditionOut] = Field(default_factory=list)
    confidence: float | None = None
    changes: list[HistoryRunChangeOut] = Field(default_factory=list)
    overlap_minutes: float | None = None
    start: datetime | None = None
    end: datetime | None = None


class HistoryConditionOut(BaseModel):
    group: str
    fact: str
    operator: str
    value: object
    passed_runs: int


class HistoryInputOut(BaseModel):
    alias: str
    metric_name: str
    analyzers: list[str] = Field(default_factory=list)
    runs_with_signals: int


class HistorySeriesOut(BaseModel):
    alias: str
    metric_name: str
    points: list[tuple[datetime, float]] = Field(default_factory=list)


class HistoryPreviewOut(BaseModel):
    service: str
    since: datetime
    verdict: str
    reason: str | None = None
    runs_checked: int
    runs_judged: int
    runs_matched: int
    conditions: list[HistoryConditionOut] = Field(default_factory=list)
    inputs: list[HistoryInputOut] = Field(default_factory=list)
    runs: list[HistoryRunOut] = Field(default_factory=list)
    series: list[HistorySeriesOut] = Field(default_factory=list)
    # Whether the chart shows every stored point in the look-back or only the newest MAX ones.
    series_truncated: bool = False
