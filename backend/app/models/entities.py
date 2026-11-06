from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Columns the analysis pipeline also writes through its own tables (intelligence/storage/
# postgres_store.py), which send no value and rely on a database default, carry server_default as
# well as default: a database built from these models alone (Helm, no sql/init.sql) had none, so
# saving any analysis failed. ensure_server_defaults adds them to databases created before.
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
    cluster: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The stored series these points belong to (run_points.series_key); each point is stored once
    # per series, by the first run that fetched it. None for CSV, OTLP and older points.
    series_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())

    __table_args__ = (
        Index("idx_ops_norm_series_ts", "series_key", "timestamp"),
        # Finds points older than the retention period (point_retention.py).
        Index("idx_ops_norm_ts", "timestamp"),
    )


class SignalEntity(Base):
    __tablename__ = "ops_operational_signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    analyzer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    env: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    status: Mapped[str] = mapped_column(String(32), default="new")
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


class CapabilityEntity(Base):
    __tablename__ = "capabilities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analyzer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


class QuestionCatalogEntity(Base):
    __tablename__ = "question_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


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
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="generic", server_default="generic")
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
    # The Prometheus connection (Mimir tenant) a run queried; None for CSV, OTLP and older runs.
    connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set when the run's points are stored by series rather than by run: its points are then the
    # series' points between start_time and end_time, some saved by earlier runs (run_points.py).
    series_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


class AnalyzerConfigSuggestionEntity(Base):
    __tablename__ = "analyzer_config_suggestions"
    __table_args__ = (
        Index("idx_analyzer_config_suggestions_analyzer", "analyzer_id"),
        Index("idx_analyzer_config_suggestions_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analyzer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lab_name: Mapped[str] = mapped_column(String(128), nullable=False)
    suggestion_name: Mapped[str] = mapped_column(String(256), nullable=False)
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    finding_rules_json: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    pass_fail_status: Mapped[str] = mapped_column(String(32), default="unknown")
    created_by: Mapped[str] = mapped_column(String(128), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AnalyzerDraftEntity(Base):
    __tablename__ = "analyzer_drafts"
    __table_args__ = (
        Index("idx_analyzer_drafts_analyzer", "analyzer_id"),
        Index("idx_analyzer_drafts_status", "status"),
        Index("idx_analyzer_drafts_updated_at", "updated_at"),
        UniqueConstraint("analyzer_id", name="uq_analyzer_drafts_analyzer_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analyzer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    readiness_json: Mapped[dict] = mapped_column(JSON, default=dict)
    routing_test_json: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_test_json: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(128), default="local")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AutonomousPolicyEntity(Base):
    __tablename__ = "autonomous_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    datasource: Mapped[str] = mapped_column(String(64), nullable=False)
    backend: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", server_default="default")
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    monitoring_categories_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    # Who made it and who last changed it (backend/app/identity.py). edited_at is separate from
    # updated_at, which every scheduled run moves.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    cluster: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    investigation_priority: Mapped[int] = mapped_column(Integer, default=3)
    signal_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    comparison_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # When the problem happened, and the first finding of the same problem (None: this is the
    # first). See intelligence/storage/postgres_store.py save_findings.
    event_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ongoing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    problem_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())
    # Optional, lazily-computed AI-polished rewrite of `summary`. Never a replacement: `summary`
    # stays the deterministic field this app has always had; ai_summary is additive and only used
    # when present, so a finding is fully functional identically to before if AI is never enabled.
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AI-written why / extra check / extra related sentence for the details page, saved on first open
    # (backend/app/services/finding_ai_wording.py). Additive like ai_summary: the template wording stays.
    ai_wording: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProblemEventEntity(Base):
    """A level change's state change: it came back (`ended`), came partly back (`partly_back`) or
    went high again (`reopened`). Written after each run (intelligence/level_endings.py), one row per
    change and never edited; read by services/active_findings.py problem_states."""

    __tablename__ = "ops_problem_events"
    # The same index as sql/init.sql and PostgresStore, so whichever creates the table first, there's one.
    __table_args__ = (Index("idx_ops_problem_event_problem", "problem_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # When the stretch that's back (or partly back, or high again) began.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When the level jumped (the problem's first level change).
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    level_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    level_during: Mapped[float | None] = mapped_column(Float, nullable=True)
    level_now: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


class FindingFeedbackEntity(Base):
    """The team's answer to "Was this real?" on one finding (services/finding_trust.py). Service and
    trust group are copied in, so a service's own rate per group is one grouped count."""

    __tablename__ = "ops_finding_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    trust_group: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    # The Grafana user who gave the current answer (backend/app/identity.py); None when it didn't
    # come through Grafana.
    answered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())


CASE_SOURCE_LINK_CHECK = (
    "(source = 'detected' AND ((finding_id IS NOT NULL) != (behavior_finding_id IS NOT NULL))) "
    "OR (source <> 'detected' AND finding_id IS NULL AND behavior_finding_id IS NULL AND source_id IS NOT NULL)"
)


class OperationalCaseEntity(Base):
    __tablename__ = "ops_operational_cases"
    __table_args__ = (
        # A detected case links to exactly one finding or behavior; an imported case
        # (docs/importing-incident-history.md) links to neither and carries its source's record ID.
        CheckConstraint(CASE_SOURCE_LINK_CHECK, name="ck_case_source_link"),
        Index("uq_case_source_record", "source", "source_id", unique=True),
        # One case per finding or behavior: two people opening a case for the same one at once
        # must get the same case, not two (see ensure_case_link_unique_schema).
        Index("idx_ops_case_finding", "finding_id", unique=True),
        Index("idx_ops_case_behavior_finding", "behavior_finding_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops_operational_findings.id", ondelete="CASCADE"),
        nullable=True,
    )
    behavior_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops_behavior_findings.id", ondelete="CASCADE"),
        nullable=True,
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
    # The person-saved write-up from Publish Knowledge: summary, likely cause, seen before, still open.
    writeup: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_indexed")
    memory_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set by "Remove from memory", cleared when the case is indexed again. Tells a case the user
    # took out of memory apart from one an outage kept out, which catch-up indexing adds back.
    memory_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    memory_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "detected" for cases Ops Signals opened itself; otherwise the system an imported case came
    # from (jira, pagerduty, csv, markdown, or a label the importer chose).
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="detected", server_default="detected")
    source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The Grafana user who opened the case, and who closed it (backend/app/identity.py); None otherwise.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_imported(self) -> bool:
        return (self.source or "detected") != "detected"


class CaseImportBatchEntity(Base):
    """One run of the incident-history importer: what was uploaded and what it did, so the
    Integrations page can show import status and a whole batch can be undone."""

    __tablename__ = "ops_case_imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    file_profiles: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class AnalyzerDivergenceEntity(Base):
    """One AI-second-opinion evaluation from the Analyzer Recommendation workbench: the router's
    top pick, the AI's independent top pick, and whether they diverged. Recorded regardless of
    whether they agreed, so a later query can compute a true divergence rate, not just outcomes
    when it happens. When analysis_run_id is present, this can be joined against
    analyzer_learning_outcomes on the same column to check whether the AI's pick or the router's
    pick actually matched the confirmed/rejected outcome - the calibration signal for whether the
    deterministic scoring rules need recalibrating."""

    __tablename__ = "analyzer_recommendation_divergences"
    __table_args__ = (
        Index("idx_analyzer_divergence_metric_name", "metric_name"),
        Index("idx_analyzer_divergence_service", "service"),
        Index("idx_analyzer_divergence_analysis_run_id", "analysis_run_id"),
        Index("idx_analyzer_divergence_diverged", "diverged"),
        Index("idx_analyzer_divergence_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    router_top_analyzer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    router_top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_top_analyzer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    diverged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    # Optional, lazily-computed plain-English rewrite of the structured facts/conditions already
    # shown for this behavior finding. Additive only - the existing summary and the raw
    # facts_json/matched_conditions_json evidence stay exactly as they are either way.
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)


class BehaviorPatternSuggestionEntity(Base):
    """A candidate behavior definition mined from historical signal co-occurrence, awaiting human
    review — same "system proposes, human approves" shape as AnalyzerConfigSuggestionEntity."""

    __tablename__ = "behavior_pattern_suggestions"
    __table_args__ = (
        Index("idx_behavior_pattern_suggestions_service", "service"),
        Index("idx_behavior_pattern_suggestions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_a: Mapped[str] = mapped_column(Text, nullable=False)
    metric_b: Mapped[str] = mapped_column(Text, nullable=False)
    co_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_a_occasions: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_b_occasions: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_strength: Mapped[float] = mapped_column(Float, nullable=False)
    sample_analysis_run_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    draft_definition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    draft_yaml_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class OtlpPendingPointEntity(Base):
    """A single metric data point received via OTLP push, buffered here between receipt and the
    next scheduled analysis cycle (backend/app/autonomous/scheduler.py). Deliberately separate
    from NormalizedPoint/ops_normalized_timeseries_points: that table holds the *output* of a
    completed analysis run (MetricAnalysisExecutor writes it), while this one is a transient
    inbox - rows are deleted once a cycle has folded them into an analysis run, so this table's
    size reflects backlog, not history."""

    __tablename__ = "otlp_pending_points"
    __table_args__ = (
        Index("idx_otlp_pending_points_service_metric", "service", "metric_name"),
        Index("idx_otlp_pending_points_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    metric_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    env: Mapped[str | None] = mapped_column(Text, nullable=True)
    host: Mapped[str | None] = mapped_column(Text, nullable=True)
    namespace: Mapped[str | None] = mapped_column(Text, nullable=True)
    pod: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ChangeEventEntity(Base):
    """A deploy/config/flag change reported by CI/CD via POST /api/events. Alert enrichment
    correlates these with an alert's change point ("started 6 min after deploy v2.3.1") - a
    temporal hint, never a claim of causation."""

    __tablename__ = "ops_change_events"
    __table_args__ = (Index("idx_change_events_service_ts", "service", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    env: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the deploy went, when CI says so. NULL means every cluster (a global or single-cluster deploy).
    cluster: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AlertEnrichmentEntity(Base):
    """One firing occurrence of an external alert (Alertmanager or generic) and what Ops Signals
    added to it. Doubles as the dedupe store (fingerprint) and the audit trail - including alerts
    whose Slack post was suppressed, so "why didn't I get a message?" has an answer."""

    __tablename__ = "ops_alert_enrichments"
    __table_args__ = (Index("idx_alert_enrichments_fingerprint", "fingerprint", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_name: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels_json: Mapped[dict] = mapped_column(JSON, default=dict)
    annotations_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generator_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    promql: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_event_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enrichment_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notify_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AssistantFeedbackEntity(Base):
    """A thumbs up or down on one Ask Ops Signals answer. Thumbs-down answers are listed on the
    Docs check page, grouped by question, as candidates for golden questions or doc fixes."""

    __tablename__ = "ops_assistant_feedback"
    __table_args__ = (Index("idx_assistant_feedback_helpful_status", "helpful", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    helpful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # wrong_section | missing_step | outdated | not_in_docs, set after the thumbs-down.
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_synthesis_used: Mapped[bool] = mapped_column(Boolean, default=False)
    # The leading sources' references ("docs/security-model.md#clients"), best first.
    cited_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # open | added_as_test | dismissed
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TicketOperationEntity(Base):
    __tablename__ = "ticket_operations"
    __table_args__ = (
        Index("idx_ticket_ops_claim", "status", "available_at"),
        Index("idx_ticket_ops_case_type", "case_id", "operation_type"),
        UniqueConstraint("provider", "idempotency_key", name="uq_ticket_ops_provider_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("ops_operational_cases.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_operation_id: Mapped[str | None] = mapped_column(ForeignKey("ticket_operations.id"), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CaseTicketLinkEntity(Base):
    __tablename__ = "case_ticket_links"
    __table_args__ = (
        UniqueConstraint("case_id", "provider", name="uq_case_ticket_links_case_provider"),
        Index("idx_ticket_links_provider_remote", "provider", "remote_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("ops_operational_cases.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    remote_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_key: Mapped[str] = mapped_column(String(128), nullable=False)
    ticket_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_remote_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CaseTicketEventEntity(Base):
    __tablename__ = "case_ticket_events"
    __table_args__ = (
        UniqueConstraint("provider", "remote_event_id", name="uq_ticket_events_prov_remote_id"),
        Index("idx_ticket_events_case_occ", "case_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("ops_operational_cases.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    remote_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TicketWebhookDeliveryEntity(Base):
    __tablename__ = "ticket_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("provider", "delivery_id", name="uq_webhook_deliv_prov_delivery"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)



class MetricUsageSnapshotEntity(Base):
    """One metric usage check: which metrics dashboards and alerts read, run every few hours."""

    __tablename__ = "metric_usage_snapshots"
    __table_args__ = (Index("idx_metric_usage_snapshots_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)  # "schedule" | "manual"
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # "completed" | "failed"
    metrics_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blind_spots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unwatched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Active series in total and in metrics nothing watches; None when they couldn't be counted.
    series_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series_unwatched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What was read (dashboards, rules, connections), queries that couldn't be resolved, warnings.
    sources_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Recording rules whose output nothing reads (metric_usage.report.UnreadRecordingRule).
    unread_rules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class MetricUsageItemEntity(Base):
    __tablename__ = "metric_usage_items"
    __table_args__ = (
        Index("idx_metric_usage_items_snapshot_status", "snapshot_id", "status"),
        Index("idx_metric_usage_items_metric_name", "metric_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("metric_usage_snapshots.id", ondelete="CASCADE"), nullable=False)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    connections_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    usages_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    via_recording_rules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    problem_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_finding_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    series: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Active series per job label per connection, the declared type, whether a recording rule makes
    # it, and when a check first listed it (None: before checks recorded that).
    jobs_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metric_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recording_rule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SlackNotificationEntity(Base):
    """One finding message for Slack and whether it arrived. Sending used to be one try with only a
    log line on failure, and a later run of the same problem counted it as reported, so a Slack
    hiccup lost the alert for good. Pending messages are retried (notifications/slack_client.py)."""

    __tablename__ = "ops_slack_notifications"
    __table_args__ = (
        Index("idx_slack_notifications_due", "status", "next_attempt_at"),
        Index("idx_slack_notifications_problem", "problem_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The problem's first finding id: a finding's problem_id, or its own id when it starts one.
    problem_key: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finding_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # pending (not sent yet, or waiting to retry) | delivered | failed (gave up after max attempts)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
