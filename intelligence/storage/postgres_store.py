from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import BOOLEAN, JSON, TIMESTAMP, Column, Float, Index, Integer, MetaData, String, Table, Text, create_engine, func, inspect, select
from sqlalchemy.dialects.postgresql import BIGINT

from intelligence.config import AppConfig
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal


class PostgresStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.engine = create_engine(self._connection_string())
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
            Column("title", Text, nullable=False),
            Column("summary", Text, nullable=False),
            Column("category", Text, nullable=False),
            Column("health_status", Text, nullable=False),
            Column("importance_score", Float, nullable=False),
            Column("investigation_priority", Integer, nullable=False),
            Column("signal_ids", JSON, nullable=False),
            Column("comparison_json", JSON, nullable=False),
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
        if not findings:
            return
        records = [finding.to_record() for finding in findings]
        with self.engine.begin() as connection:
            connection.execute(self.findings_table.insert(), records)

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
            connection.execute(self.question_catalog_table.delete())
            for question in questions:
                connection.execute(
                    self.question_catalog_table.insert().values(
                        id=question["id"],
                        label=question["label"],
                        description=question["description"],
                        enabled=bool(question.get("enabled", True)),
                        display_order=question.get("display_order", 0),
                    )
                )

    def create_analysis_run(self, payload: dict[str, Any]) -> None:
        column_names = {column["name"] for column in inspect(self.engine).get_columns("analysis_runs", schema=None)}
        filtered_payload = {key: value for key, value in payload.items() if key in column_names}
        with self.engine.begin() as connection:
            connection.execute(self.analysis_runs_table.insert().values(**filtered_payload))

    def update_analysis_run_learning_snapshot(self, analysis_run_id: str, payload: dict[str, Any]) -> None:
        column_names = {column["name"] for column in inspect(self.engine).get_columns("analysis_runs", schema=None)}
        allowed = {
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
