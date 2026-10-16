from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import pandas as pd
from sqlalchemy import BOOLEAN, JSON, TIMESTAMP, Column, Float, Index, Integer, MetaData, String, Table, Text, create_engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from intelligence.config import AppConfig
from intelligence.findings.schema import OperationalFinding
from intelligence.storage.database_url import database_url_from_env
from intelligence.signals.schema import OperationalSignal

logger = logging.getLogger(__name__)

# Two findings are the same problem when they describe the same series (service, metric, cluster,
# connection) the same way (title) and their events overlap, give or take this much: a later run,
# with more data, can date the same event a few steps differently.
PROBLEM_MATCH_TOLERANCE = timedelta(minutes=10)
_HEALTH_RANK = {"normal": 0, "significant": 1, "critical": 2}

# Optional post-write hook, set via register_findings_hook(). Kept generic (not
# Slack-specific) so this storage layer stays framework-agnostic — it doesn't know or
# care what consumes the signal, only that findings were just persisted.
_on_findings_saved: Callable[[list[OperationalFinding]], None] | None = None


def register_findings_hook(callback: Callable[[list[OperationalFinding]], None] | None) -> None:
    """Register a callback invoked with every batch of findings right after they're saved.

    Best-effort: an exception raised by the callback is logged and swallowed by
    save_findings, never propagated, so a broken downstream integration can never fail
    the analysis pipeline that just produced these findings.
    """
    global _on_findings_saved
    _on_findings_saved = callback


# Set by callers that do their own notification for the run they're about to execute (alert
# enrichment posts one combined Slack message per alert), so the generic hook doesn't post a
# second, plain message for the same findings. A ContextVar so it only covers the calling
# thread/task, never a concurrent autonomous run.
_findings_hook_suppressed: ContextVar[bool] = ContextVar("findings_hook_suppressed", default=False)


@contextmanager
def suppress_findings_hook() -> Iterator[None]:
    token = _findings_hook_suppressed.set(True)
    try:
        yield
    finally:
        _findings_hook_suppressed.reset(token)


# One engine, and so one connection pool, per database URL for the whole process. Every analysis
# builds a PostgresStore (each CSV upload, Prometheus run and OTLP metric group); with an engine
# each, never closed, an OTLP cycle over a real Collector's hundreds of groups ran Postgres out of
# connections. In-memory SQLite stays one engine per store: each is its own fresh database.
_shared_engines: dict[str, Engine] = {}
_shared_engines_lock = threading.Lock()


def _engine_for(url: str) -> Engine:
    if ":memory:" in url:
        return create_engine(url)
    with _shared_engines_lock:
        engine = _shared_engines.get(url)
        if engine is None:
            # pre_ping: a pooled connection the database closed (restart, idle timeout) is
            # replaced rather than failing the next analysis.
            engine = create_engine(url, pool_pre_ping=True)
            _shared_engines[url] = engine
        return engine


class PostgresStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.engine = _engine_for(self._connection_string())
        self.metadata = MetaData()
        prefix = config.storage.postgres.table_prefix
        self.normalized_table = Table(
            f"{prefix}normalized_timeseries_points",
            self.metadata,
            Column("id", BIGINT, primary_key=True, autoincrement=True),
            Column("source", Text),
            Column("metric_name", Text, nullable=False),
            Column("timestamp", TIMESTAMP(timezone=True), nullable=False),
            Column("value", Float, nullable=False),
            Column("service", Text),
            Column("env", Text),
            Column("host", Text),
            Column("namespace", Text),
            Column("pod", Text),
            Column("unit", Text),
            Column("metric_type", Text),
            Column("cluster", Text),
            Column("tags_json", JSON),
            Column("analysis_run_id", Text),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )
        Index(f"idx_{prefix}norm_metric_ts", self.normalized_table.c.metric_name, self.normalized_table.c.timestamp)
        Index(f"idx_{prefix}norm_service_ts", self.normalized_table.c.service, self.normalized_table.c.timestamp)
        Index(f"idx_{prefix}norm_env_ts", self.normalized_table.c.env, self.normalized_table.c.timestamp)

        self.signals_table = Table(
            f"{prefix}operational_signals",
            self.metadata,
            Column("id", BIGINT, primary_key=True, autoincrement=True),
            Column("signal_id", Text),
            Column("signal_type", Text, nullable=False),
            Column("analyzer_id", Text),
            Column("metric_name", Text, nullable=False),
            Column("service", Text),
            Column("env", Text),
            Column("cluster", Text),
            Column("severity", Text),
            Column("confidence", Float),
            Column("start_time", TIMESTAMP(timezone=True)),
            Column("end_time", TIMESTAMP(timezone=True)),
            Column("summary", Text),
            Column("evidence_json", JSON),
            Column("importance_score", Float, nullable=False, server_default="0"),
            Column("status", String, nullable=False, default="new"),
            Column("embedding_json", JSON),
            Column("analysis_run_id", Text),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )
        Index(f"idx_{prefix}signal_uid", self.signals_table.c.signal_id, unique=True)
        Index(f"idx_{prefix}signal_metric_start", self.signals_table.c.metric_name, self.signals_table.c.start_time)
        Index(f"idx_{prefix}signal_service_start", self.signals_table.c.service, self.signals_table.c.start_time)
        Index(f"idx_{prefix}signal_env_start", self.signals_table.c.env, self.signals_table.c.start_time)
        Index(f"idx_{prefix}signal_status", self.signals_table.c.status)

        self.findings_table = Table(
            f"{prefix}operational_findings",
            self.metadata,
            Column("id", BIGINT, primary_key=True, autoincrement=True),
            Column("analysis_run_id", Text),
            Column("service", Text),
            Column("metric_name", Text, nullable=False),
            Column("cluster", Text),
            Column("title", Text, nullable=False),
            Column("summary", Text, nullable=False),
            Column("category", Text, nullable=False),
            Column("health_status", Text, nullable=False),
            Column("importance_score", Float, nullable=False),
            Column("investigation_priority", Integer, nullable=False),
            Column("signal_ids", JSON, nullable=False),
            Column("comparison_json", JSON, nullable=False),
            Column("event_start", TIMESTAMP(timezone=True)),
            Column("event_end", TIMESTAMP(timezone=True)),
            Column("ongoing", BOOLEAN),
            Column("problem_id", BIGINT),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )
        Index(f"idx_{prefix}finding_metric", self.findings_table.c.metric_name, self.findings_table.c.created_at)
        Index(f"idx_{prefix}finding_service", self.findings_table.c.service, self.findings_table.c.created_at)
        Index(f"idx_{prefix}finding_importance", self.findings_table.c.importance_score)

        self.capabilities_table = Table(
            "capabilities",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("analyzer_id", String(64), nullable=False),
            Column("title", String(128), nullable=False),
            Column("description", Text, nullable=False),
            Column("enabled", BOOLEAN, nullable=False, default=True),
            Column("metadata_json", JSON, nullable=False, default=dict),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
            Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )

        self.question_catalog_table = Table(
            "question_catalog",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("label", String(256), nullable=False),
            Column("description", Text, nullable=False),
            Column("enabled", BOOLEAN, nullable=False, default=True),
            Column("display_order", Integer, nullable=False, default=0),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )

        self.capability_questions_table = Table(
            "capability_questions",
            self.metadata,
            Column("capability_id", String(64), nullable=False),
            Column("question_id", String(64), nullable=False),
        )

        self.analysis_runs_table = Table(
            "analysis_runs",
            self.metadata,
            Column("id", String(64), primary_key=True),
            Column("source_type", String(32), nullable=False),
            Column("file_name", String(255)),
            Column("provider", String(32), nullable=False, server_default="generic"),
            Column("service", String(128), nullable=False),
            Column("metric_name", String(128), nullable=False),
            Column("start_time", TIMESTAMP(timezone=True), nullable=False),
            Column("end_time", TIMESTAMP(timezone=True), nullable=False),
            Column("sample_count", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("router_version", String(100)),
            Column("feature_extractor_version", String(100)),
            Column("analyzer_registry_version", String(100)),
            Column("series_profile_json", JSON),
            Column("router_decisions_json", JSON),
            Column("executed_analyzers_json", JSON),
            Column("generated_findings_json", JSON),
            Column("connection_id", String(64)),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )

        self.question_answers_table = Table(
            "question_answers",
            self.metadata,
            Column("id", BIGINT, primary_key=True, autoincrement=True),
            Column("analysis_run_id", String(64), nullable=False),
            Column("question_id", String(64), nullable=False),
            Column("headline", Text, nullable=False),
            Column("answer", Text, nullable=False),
            Column("status", String(32), nullable=False),
            Column("priority", String(32), nullable=False),
            Column("confidence", Float, nullable=False),
            Column("key_points_json", JSON, nullable=False),
            Column("evidence_signal_ids", JSON, nullable=False),
            Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
        )

    def _connection_string(self) -> str:
        # Same variable the backend API uses (backend/app/config.py), so a deployment that points
        # the backend at its database (compose, Helm) doesn't also need a config.yaml edit for
        # analysis runs to reach it.
        url = database_url_from_env()
        if url:
            return url
        pg = self.config.storage.postgres
        return f"postgresql+psycopg://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.database}"

    def init_db(self) -> None:
        self.metadata.create_all(self.engine)

    def init_db_from_sql(self, sql_path: Path) -> None:
        sql_text = sql_path.read_text(encoding="utf-8")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(sql_text)

    def save_normalized_points(self, dataframe: pd.DataFrame, analysis_run_id: str | None = None) -> None:
        if analysis_run_id:
            dataframe = dataframe.copy()
            dataframe["analysis_run_id"] = analysis_run_id
        records = dataframe.to_dict(orient="records")
        with self.engine.begin() as connection:
            connection.execute(self.normalized_table.insert(), records)

    def save_signals(self, signals: list[OperationalSignal], embeddings: dict[int, Any] | None = None) -> None:
        records: list[dict[str, Any]] = []
        for index, signal in enumerate(signals):
            record = signal.to_dict()
            record["embedding_json"] = embeddings.get(index) if embeddings else None
            records.append(record)
        if not records:
            return
        with self.engine.begin() as connection:
            connection.execute(self.signals_table.insert(), records)

    def save_findings(self, findings: list[OperationalFinding]) -> None:
        """Saves findings, linking each to the problem an earlier run already reported (problem_id).
        The hook (Slack) only hears of new problems and of problems that got worse, not of every
        run that sees the same problem again."""
        if not findings:
            return
        with self.engine.begin() as connection:
            to_notify = self._link_problems(connection, findings)
            connection.execute(self.findings_table.insert(), [finding.to_record() for finding in findings])
        if to_notify and _on_findings_saved is not None and not _findings_hook_suppressed.get():
            try:
                _on_findings_saved(to_notify)
            except Exception:
                logger.warning("findings hook raised", exc_info=True)

    def _link_problems(self, connection, findings: list[OperationalFinding]) -> list[OperationalFinding]:
        run_ids = {finding.analysis_run_id for finding in findings if finding.analysis_run_id}
        runs = self.analysis_runs_table
        connection_ids = (
            dict(connection.execute(select(runs.c.id, runs.c.connection_id).where(runs.c.id.in_(run_ids))).all()) if run_ids else {}
        )
        to_notify: list[OperationalFinding] = []
        for finding in findings:
            earlier = self._earlier_finding_of_same_problem(connection, finding, connection_ids.get(finding.analysis_run_id))
            if earlier is None:
                to_notify.append(finding)
                continue
            earlier_id, earlier_problem_id = earlier
            finding.problem_id = earlier_problem_id or earlier_id
            if _HEALTH_RANK.get(finding.health_status, 0) > self._worst_health(connection, finding.problem_id):
                to_notify.append(finding)
        return to_notify

    def _earlier_finding_of_same_problem(self, connection, finding: OperationalFinding, connection_id: str | None) -> tuple[int, int | None] | None:
        if finding.event_start is None or finding.event_end is None:
            return None
        findings, runs = self.findings_table, self.analysis_runs_table

        def same(column, value):
            return column.is_(None) if value is None else column == value

        query = (
            select(findings.c.id, findings.c.problem_id)
            .select_from(findings.outerjoin(runs, findings.c.analysis_run_id == runs.c.id))
            .where(
                findings.c.metric_name == finding.metric_name,
                findings.c.title == finding.title,
                same(findings.c.service, finding.service),
                same(findings.c.cluster, finding.cluster),
                same(runs.c.connection_id, connection_id),
                findings.c.event_end >= finding.event_start - PROBLEM_MATCH_TOLERANCE,
                findings.c.event_start <= finding.event_end + PROBLEM_MATCH_TOLERANCE,
            )
            .order_by(findings.c.created_at.desc(), findings.c.id.desc())
            .limit(1)
        )
        row = connection.execute(query).first()
        return (row[0], row[1]) if row else None

    def _worst_health(self, connection, problem_id: int) -> int:
        findings = self.findings_table
        statuses = connection.execute(
            select(findings.c.health_status).where((findings.c.id == problem_id) | (findings.c.problem_id == problem_id))
        ).scalars()
        return max((_HEALTH_RANK.get(status, 0) for status in statuses), default=0)

    def fetch_signals(self) -> pd.DataFrame:
        with self.engine.begin() as connection:
            result = connection.execute(select(self.signals_table)).mappings().all()
        return pd.DataFrame(result)

    def fetch_normalized_points(self) -> pd.DataFrame:
        with self.engine.begin() as connection:
            result = connection.execute(select(self.normalized_table)).mappings().all()
        return pd.DataFrame(result)

    def fetch_findings(self) -> pd.DataFrame:
        with self.engine.begin() as connection:
            result = connection.execute(select(self.findings_table).order_by(self.findings_table.c.importance_score.desc())).mappings().all()
        return pd.DataFrame(result)

    def fetch_signals_for_ids(self, signal_ids: list[str]) -> pd.DataFrame:
        if not signal_ids:
            return pd.DataFrame()
        with self.engine.begin() as connection:
            result = (
                connection.execute(select(self.signals_table).where(self.signals_table.c.signal_id.in_(signal_ids))).mappings().all()
            )
        return pd.DataFrame(result)

    def save_capabilities(self, capabilities: list[dict[str, Any]]) -> None:
        if not capabilities:
            return
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                # Every analysis run rewrites this catalog, and runs overlap (API uploads, the
                # scheduler, alert enrichment). Two rewrites at once hit duplicate keys or
                # deadlocked, failing one whole run. The lock makes them take turns for the few
                # milliseconds this takes; reads still go through. SQLite allows one writer anyway.
                preparer = self.engine.dialect.identifier_preparer
                tables = ", ".join(preparer.format_table(table) for table in (self.capabilities_table, self.capability_questions_table))
                connection.execute(text(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE"))
            connection.execute(self.capabilities_table.delete())
            connection.execute(self.capability_questions_table.delete())
            for capability in capabilities:
                record = {
                    "id": capability["id"],
                    "analyzer_id": capability["analyzer_id"],
                    "title": capability["title"],
                    "description": capability["description"],
                    "enabled": bool(capability.get("enabled", True)),
                    "metadata_json": {"supported_question_ids": capability.get("supported_question_ids", [])},
                }
                connection.execute(self.capabilities_table.insert().values(**record))
                for qid in capability.get("supported_question_ids", []):
                    connection.execute(
                        self.capability_questions_table.insert().values(
                            capability_id=capability["id"],
                            question_id=qid,
                        )
                    )

    def save_questions(self, questions: list[dict[str, Any]]) -> None:
        if not questions:
            return
        with self.engine.begin() as connection:
            for question in questions:
                record = {
                    "id": question["id"],
                    "label": question["label"],
                    "description": question["description"],
                    "enabled": bool(question.get("enabled", True)),
                    "display_order": question.get("display_order", 0),
                }
                if self.engine.dialect.name == "postgresql":
                    statement = postgres_insert(self.question_catalog_table).values(**record)
                    statement = statement.on_conflict_do_update(
                        index_elements=[self.question_catalog_table.c.id],
                        set_={
                            "label": statement.excluded.label,
                            "description": statement.excluded.description,
                            "enabled": statement.excluded.enabled,
                            "display_order": statement.excluded.display_order,
                        },
                    )
                    connection.execute(statement)
                elif self.engine.dialect.name == "sqlite":
                    statement = sqlite_insert(self.question_catalog_table).values(**record)
                    statement = statement.on_conflict_do_update(
                        index_elements=[self.question_catalog_table.c.id],
                        set_={
                            "label": statement.excluded.label,
                            "description": statement.excluded.description,
                            "enabled": statement.excluded.enabled,
                            "display_order": statement.excluded.display_order,
                        },
                    )
                    connection.execute(statement)
                else:
                    connection.execute(self.question_catalog_table.insert().values(**record))

    def create_analysis_run(self, payload: dict[str, Any]) -> None:
        column_names = {column["name"] for column in inspect(self.engine).get_columns("analysis_runs", schema=None)}
        filtered_payload = {key: value for key, value in payload.items() if key in column_names}
        with self.engine.begin() as connection:
            connection.execute(self.analysis_runs_table.insert().values(**filtered_payload))

    def update_analysis_run_learning_snapshot(self, analysis_run_id: str, payload: dict[str, Any]) -> None:
        column_names = {column["name"] for column in inspect(self.engine).get_columns("analysis_runs", schema=None)}
        allowed = {
            "status",
            "router_version",
            "feature_extractor_version",
            "analyzer_registry_version",
            "series_profile_json",
            "router_decisions_json",
            "executed_analyzers_json",
            "generated_findings_json",
        }
        filtered_payload = {key: value for key, value in payload.items() if key in column_names and key in allowed}
        if not filtered_payload:
            return
        with self.engine.begin() as connection:
            connection.execute(
                self.analysis_runs_table.update()
                .where(self.analysis_runs_table.c.id == analysis_run_id)
                .values(**filtered_payload)
            )

    def save_question_answers(self, answers: list[dict[str, Any]]) -> None:
        if not answers:
            return
        with self.engine.begin() as connection:
            connection.execute(self.question_answers_table.insert(), answers)
