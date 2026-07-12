from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="generic")
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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
