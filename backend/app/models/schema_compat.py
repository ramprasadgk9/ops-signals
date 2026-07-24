from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


ANALYSIS_RUN_COLUMN_SQL = {
    "router_version": "VARCHAR(100)",
    "feature_extractor_version": "VARCHAR(100)",
    "analyzer_registry_version": "VARCHAR(100)",
    "series_profile_json": "JSON",
    "router_decisions_json": "JSON",
    "executed_analyzers_json": "JSON",
    "generated_findings_json": "JSON",
}


def ensure_learning_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "analysis_runs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("analysis_runs")}
    missing = {name: ddl for name, ddl in ANALYSIS_RUN_COLUMN_SQL.items() if name not in existing}
    if not missing:
        return

    dialect = engine.dialect.name
    with engine.begin() as connection:
        for name, ddl in missing.items():
            if dialect == "sqlite":
                sqlite_type = "TEXT" if ddl == "JSON" else ddl
                connection.execute(text(f"ALTER TABLE analysis_runs ADD COLUMN {name} {sqlite_type}"))
            else:
                connection.execute(text(f"ALTER TABLE analysis_runs ADD COLUMN {name} {ddl}"))

