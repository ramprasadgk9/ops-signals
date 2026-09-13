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


# Nullable, additive columns caching an optional AI-polished version of existing deterministic
# text (finding summary, behavior explanation) - never read as a replacement, only ever as "if
# present, prefer this; otherwise use the existing deterministic field unchanged."
_AI_NARRATIVE_COLUMNS = {
    "ops_operational_findings": {"ai_summary": "TEXT"},
    "ops_behavior_findings": {"ai_explanation": "TEXT"},
}


def ensure_ai_narrative_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table_name, column_sql in _AI_NARRATIVE_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = {name: ddl for name, ddl in column_sql.items() if name not in existing_columns}
        if not missing:
            continue
        with engine.begin() as connection:
            for name, ddl in missing.items():
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))

