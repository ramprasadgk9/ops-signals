from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class MonitoringCategory(str, Enum):
    performance = "performance"
    capacity = "capacity"
    availability = "availability"
    reliability = "reliability"
    infrastructure = "infrastructure"
    messaging = "messaging"
    kubernetes = "kubernetes"
    custom = "custom"


class MetricConcept(str, Enum):
    latency = "latency"
    throughput = "throughput"
    request_rate = "request_rate"
    processing_duration = "processing_duration"
    cpu = "cpu"
    memory = "memory"
    disk = "disk"
    saturation = "saturation"
    queue_depth = "queue_depth"
    health = "health"
    uptime = "uptime"
    error_rate = "error_rate"
    success_rate = "success_rate"
    failed_requests = "failed_requests"
    timeout = "timeout"
    retry = "retry"
    exception = "exception"
    restart = "restart"
    failed_operation = "failed_operation"
    node = "node"
    container = "container"
    filesystem = "filesystem"
    network = "network"
    volume = "volume"
    host_load = "host_load"
    consumer_lag = "consumer_lag"
    publish_rate = "publish_rate"
    consume_rate = "consume_rate"
    failed_messages = "failed_messages"
    pod_restart = "pod_restart"
    deployment_availability = "deployment_availability"
    pending_pod = "pending_pod"
    container_waiting = "container_waiting"
    replica_mismatch = "replica_mismatch"
    oom_kill = "oom_kill"
    custom = "custom"


class AnalysisScope(BaseModel):
    environment: str | None = None
    environment_label: str | None = "env"
    services: list[str] = Field(default_factory=list)
    all_services: bool = True
    service_label: str = "service"
    namespaces: list[str] = Field(default_factory=list)
    all_namespaces: bool = True
    namespace_label: str | None = "namespace"
    max_series_per_metric: int = Field(default=10, ge=1, le=5000)
    metadata_limit: int = Field(default=5000, ge=10, le=50000)


class ExecutionPolicy(BaseModel):
    interval: str = "10m"
    analysis_window: str = "24h"
    max_metrics_per_run: int = Field(default=500, ge=1, le=5000)
    max_parallel_jobs: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Reserved for future worker concurrency. Execution currently runs sequentially.",
    )


class CustomMetricConstraints(BaseModel):
    explicit_metrics: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    required_labels: dict[str, str] = Field(default_factory=dict)
    aggregation: str | None = None
    group_by: list[str] = Field(default_factory=list)


class MonitoringSelection(BaseModel):
    categories: list[MonitoringCategory] = Field(min_length=1)
    custom_constraints: CustomMetricConstraints | None = None


class AutonomousAnalysisPolicy(BaseModel):
    id: str | None = None
    name: str = "Preview policy"
    datasource: str = "prometheus"
    backend: str = "grafana-stack"
    scope: AnalysisScope = Field(default_factory=AnalysisScope)
    monitoring_selection: MonitoringSelection = Field(
        default_factory=lambda: MonitoringSelection(categories=[MonitoringCategory.performance])
    )
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    enabled: bool = False
    schedule_minutes: int | None = Field(default=None, ge=1)
    next_run_at: datetime | None = None
    last_run_status: str | None = None
    consecutive_failures: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AutonomousPreviewRequest(BaseModel):
    datasource: str = "prometheus"
    backend: str = "grafana-stack"
    scope: AnalysisScope = Field(default_factory=AnalysisScope)
    monitoring_selection: MonitoringSelection | None = None
    # Backward-compatible fields used by the current plugin build.
    monitoring_categories: list[MonitoringCategory] | None = None
    custom_constraints: CustomMetricConstraints | None = None
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @field_validator("datasource")
    @classmethod
    def datasource_must_be_prometheus(cls, value: str) -> str:
        if value.lower() != "prometheus":
            raise ValueError("only prometheus datasource preview is supported")
        return value

    @model_validator(mode="after")
    def normalize_monitoring_selection(self) -> "AutonomousPreviewRequest":
        if self.monitoring_selection is None:
            categories = self.monitoring_categories or []
            self.monitoring_selection = MonitoringSelection(
                categories=categories,
                custom_constraints=self.custom_constraints or CustomMetricConstraints(),
            )
        elif self.monitoring_selection.custom_constraints is None:
            self.monitoring_selection.custom_constraints = self.custom_constraints or CustomMetricConstraints()
        return self

    @property
    def selected_categories(self) -> list[MonitoringCategory]:
        return self.monitoring_selection.categories if self.monitoring_selection else []

    @property
    def selected_custom_constraints(self) -> CustomMetricConstraints:
        if self.monitoring_selection and self.monitoring_selection.custom_constraints:
            return self.monitoring_selection.custom_constraints
        return CustomMetricConstraints()


class DiscoveredMetric(BaseModel):
    metric_name: str
    metric_type: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    services: list[str] = Field(default_factory=list)
    namespaces: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    # Backward-compatible singulars used by existing tests/UI.
    service: str | None = None
    namespace: str | None = None
    environment: str | None = None
    last_seen: datetime | None = None
    source: str = "prometheus"
    estimated_series_count: int | None = None
    cardinality_estimate: int | None = None
    referenced_by_alert_rule: bool = False
    referenced_by_recording_rule: bool = False
    referenced_by_dashboard: bool = False

    @model_validator(mode="after")
    def fill_logical_values(self) -> "DiscoveredMetric":
        if self.service and self.service not in self.services:
            self.services.append(self.service)
        if self.namespace and self.namespace not in self.namespaces:
            self.namespaces.append(self.namespace)
        if self.environment and self.environment not in self.environments:
            self.environments.append(self.environment)
        if self.services and not self.service:
            self.service = self.services[0]
        if self.namespaces and not self.namespace:
            self.namespace = self.namespaces[0]
        if self.environments and not self.environment:
            self.environment = self.environments[0]
        if self.estimated_series_count is None and self.cardinality_estimate is not None:
            self.estimated_series_count = self.cardinality_estimate
        if self.cardinality_estimate is None and self.estimated_series_count is not None:
            self.cardinality_estimate = self.estimated_series_count
        return self


class MetricDiscoveryResult(BaseModel):
    metrics: list[DiscoveredMetric] = Field(default_factory=list)
    series_available: int | None = None
    series_discovered: int = 0
    truncated: bool = False
    starved_metrics: list[str] = Field(default_factory=list)


class ResolvedAnalysisScope(BaseModel):
    resolved_services: list[str] = Field(default_factory=list)
    resolved_namespaces: list[str] = Field(default_factory=list)
    resolved_environment: str | None = None
    discovered_metric_count: int = 0
    series_discovered: int = 0
    series_available: int | None = None
    truncated: bool = False
    starved_metrics_count: int = 0
    starved_metrics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    filters_applied: dict[str, object] = Field(default_factory=dict)
    label_mapping: dict[str, str | None] = Field(default_factory=dict)
    selector: str = ""


class QueryStrategy(BaseModel):
    transformation: str = "raw"
    range: str | None = None
    quantile: float | None = None
    aggregation: str = "avg"
    group_by: list[str] = Field(default_factory=lambda: ["service"])


class MetricClassification(BaseModel):
    metric_name: str
    categories: list[MonitoringCategory] = Field(default_factory=list)
    would_be_category: list[MonitoringCategory] = Field(default_factory=list)
    concepts: list[MetricConcept] = Field(default_factory=list)
    confidence: float = 0.0
    selection_reason: str | None = None
    matched_rule: str | None = None
    suggested_query_strategy: QueryStrategy = Field(default_factory=QueryStrategy)
    selected: bool = False
    exclusion_reason: str | None = None


class PlannedAnalysisRequest(BaseModel):
    trigger: Literal["autonomous_preview"] = "autonomous_preview"
    datasource: str = "prometheus"
    backend: str = "grafana-stack"
    metric_identity: dict[str, Any]
    query: dict[str, Any]
    analysis_window: str
    classification_confidence: float
    selection_reason: str | None = None
    execution_options: dict[str, Any] = Field(default_factory=dict)


class MetricPlanItem(BaseModel):
    service: str | None = None
    namespace: str | None = None
    environment: str | None = None
    metric_name: str
    category: MonitoringCategory | None = None
    concept: MetricConcept | None = None
    would_be_category: list[MonitoringCategory] = Field(default_factory=list)
    concepts: list[MetricConcept] = Field(default_factory=list)
    metric_type: str | None = None
    selector: str = ""
    transformation: str = "raw"
    aggregation: str = "avg_by_service"
    aggregation_strategy: str = "avg_by_service"
    group_by: list[str] = Field(default_factory=list)
    promql: str = ""
    confidence: float = 0.0
    selection_reason: str | None = None
    matched_rule: str | None = None
    estimated_series_count: int = 1
    planned: bool = False
    exclusion_reason: str | None = None
    analysis_window: str
    explanation: str | None = None
    planned_request: PlannedAnalysisRequest | None = None


class MetricAnalysisPlan(BaseModel):
    scope_summary: dict[str, Any] = Field(default_factory=dict)
    monitoring_summary: dict[str, Any] = Field(default_factory=dict)
    total_metrics_discovered: int
    total_metrics_classified: int
    total_metrics_selected: int
    total_metrics_excluded: int
    planned_jobs: int
    budget_limited_jobs: int
    budget_excluded_metrics_count: int = 0
    budget_excluded_metrics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    items: list[MetricPlanItem] = Field(default_factory=list)


class AutonomousPreviewResponse(BaseModel):
    scope_summary: dict[str, Any]
    monitoring_summary: dict[str, Any] = Field(default_factory=dict)
    metrics_discovered: int
    metrics_classified: int = 0
    metrics_selected: int = 0
    # Backward-compatible names used by existing UI.
    metrics_matched: int = 0
    metrics_excluded: int
    planned_jobs: int
    budget_limited_jobs: int = 0
    budget_limited: int = 0
    budget_excluded_metrics_count: int = 0
    budget_excluded_metrics: list[str] = Field(default_factory=list)
    series_discovered: int = 0
    series_available: int | None = None
    truncated: bool = False
    starved_metrics_count: int = 0
    starved_metrics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    items: list[MetricPlanItem] = Field(default_factory=list)


class AutonomousRunRequest(AutonomousPreviewRequest):
    dry_run: bool = False


class AutonomousJobRunResult(BaseModel):
    job_id: str | None = None
    metric_name: str
    service: str | None = None
    namespace: str | None = None
    category: MonitoringCategory | None = None
    concept: MetricConcept | None = None
    promql: str
    status: Literal["completed", "skipped", "failed"]
    skip_reason_code: str | None = None
    skip_reason: str | None = None
    analysis_run_id: str | None = None
    duration_ms: int | None = None
    sample_count: int = 0
    series_count: int = 0
    signal_count: int = 0
    findings_count: int = 0
    behavior_findings_count: int = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AutonomousRunResponse(BaseModel):
    policy_run_id: str | None = None
    status: Literal["completed", "partial", "failed", "dry_run"]
    planned_jobs: int
    executed_jobs: int
    skipped_jobs: int
    failed_jobs: int
    budget_limited_jobs: int = 0
    budget_excluded_metrics_count: int = 0
    budget_excluded_metrics: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    analysis_window: str
    requested_start: datetime
    requested_end: datetime
    step: str
    preview: AutonomousPreviewResponse
    results: list[AutonomousJobRunResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
