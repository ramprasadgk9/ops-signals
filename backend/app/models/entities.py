from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class NormalizedPoint(Base):
    __tablename__ = "ops_normalized_timeseries_points"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    env: Mapped[str | None] = mapped_column(Text, nullable=True)
    host: Mapped[str | None] = mapped_column(Text, nullable=True)
    namespace: Mapped[str | None] = mapped_column(Text, nullable=True)
    pod: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SignalEntity(Base):
    __tablename__ = "ops_operational_signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    analyzer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    env: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="new")
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CapabilityEntity(Base):
    __tablename__ = "capabilities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analyzer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class QuestionCatalogEntity(Base):
    __tablename__ = "question_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CapabilityQuestionEntity(Base):
    __tablename__ = "capability_questions"

    capability_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("capabilities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    question_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("question_catalog.id", ondelete="CASCADE"),
        primary_key=True,
    )


class AnalysisRunEntity(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="generic")
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    router_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feature_extractor_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyzer_registry_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    series_profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    router_decisions_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    executed_analyzers_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    generated_findings_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AutonomousPolicyEntity(Base):
    __tablename__ = "autonomous_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    datasource: Mapped[str] = mapped_column(String(64), nullable=False)
    backend: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    monitoring_categories_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AutonomousPolicyRunEntity(Base):
    __tablename__ = "autonomous_policy_runs"
    __table_args__ = (
        Index("idx_autonomous_policy_runs_policy_id", "policy_id"),
        Index("idx_autonomous_policy_runs_status", "status"),
        Index("idx_autonomous_policy_runs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("autonomous_policies.id", ondelete="SET NULL"), nullable=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metrics_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_selected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AutonomousMetricJobEntity(Base):
    __tablename__ = "autonomous_analysis_jobs"
    __table_args__ = (
        Index("idx_autonomous_jobs_policy_run_id", "policy_run_id"),
        Index("idx_autonomous_jobs_status", "status"),
        Index("idx_autonomous_jobs_analysis_run_id", "analysis_run_id"),
        Index("idx_autonomous_jobs_service", "service"),
        Index("idx_autonomous_jobs_metric_name", "metric_name"),
        Index("idx_autonomous_jobs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("autonomous_policy_runs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    datasource: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    namespace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    logical_metric_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promql: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_window: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregation_strategy: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transformation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    skip_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skip_reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FindingEntity(Base):
    __tablename__ = "ops_operational_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    investigation_priority: Mapped[int] = mapped_column(Integer, default=3)
    signal_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    comparison_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class QuestionAnswerEntity(Base):
    __tablename__ = "question_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("question_catalog.id", ondelete="CASCADE"),
        nullable=False,
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    key_points_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_signal_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class OperationalCaseEntity(Base):
    __tablename__ = "ops_operational_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("ops_operational_findings.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    case_title: Mapped[str] = mapped_column(Text, nullable=False)
    case_status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    finding_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    investigation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    investigation_notes: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    root_cause_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    root_cause_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    root_cause_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_indexed")
    memory_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyzerLearningOutcomeEntity(Base):
    __tablename__ = "analyzer_learning_outcomes"
    __table_args__ = (
        CheckConstraint(
            "outcome_status IN ('confirmed', 'partially_confirmed', 'rejected', 'inconclusive')",
            name="analyzer_learning_outcomes_status_check",
        ),
        UniqueConstraint("case_id", "finding_id", name="uq_analyzer_learning_case_finding"),
        Index("idx_analyzer_learning_analysis_run_id", "analysis_run_id"),
        Index("idx_analyzer_learning_case_id", "case_id"),
        Index("idx_analyzer_learning_finding_id", "finding_id"),
        Index("idx_analyzer_learning_metric_name", "metric_name"),
        Index("idx_analyzer_learning_service_id", "service_id"),
        Index("idx_analyzer_learning_organization_id", "organization_id"),
        Index("idx_analyzer_learning_outcome_status", "outcome_status"),
        Index("idx_analyzer_learning_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    router_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feature_extractor_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyzer_registry_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    series_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    router_decisions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    executed_analyzers: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    generated_findings: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    outcome_status: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_analyzers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    rejected_analyzers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class BehaviorFindingEntity(Base):
    __tablename__ = "ops_behavior_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    behavior_id: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_id: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    matched_conditions_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    correlation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
