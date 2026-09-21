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


AUTONOMOUS_POLICY_SCHEDULING_COLUMN_SQL = {
    "schedule_minutes": "INTEGER",
    "next_run_at": "TIMESTAMPTZ",
    "last_run_status": "VARCHAR(32)",
    "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
}


def ensure_autonomous_policy_scheduling_schema(engine: Engine) -> None:
    """Adds the columns the recurring-schedule feature needs to the existing autonomous_policies
    table, which previously had an `enabled` flag but no repository, endpoint, or scheduler ever
    read or wrote it - this wires it up additively rather than replacing it."""
    inspector = inspect(engine)
    if "autonomous_policies" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("autonomous_policies")}
    missing = {name: ddl for name, ddl in AUTONOMOUS_POLICY_SCHEDULING_COLUMN_SQL.items() if name not in existing}
    if not missing:
        return

    dialect = engine.dialect.name
    with engine.begin() as connection:
        for name, ddl in missing.items():
            if dialect == "sqlite":
                sqlite_type = "DATETIME" if ddl == "TIMESTAMPTZ" else ddl
                connection.execute(text(f"ALTER TABLE autonomous_policies ADD COLUMN {name} {sqlite_type}"))
            else:
                connection.execute(text(f"ALTER TABLE autonomous_policies ADD COLUMN {name} {ddl}"))


def ensure_case_behavior_link_schema(engine: Engine) -> None:
    """Lets a case originate from a BehaviorFinding (a correlated, cross-metric root-cause
    story) instead of only a single-metric Finding, which is all the original schema
    supported. Adds the new nullable link column and, on Postgres, relaxes finding_id's
    NOT NULL constraint so a behavior-sourced case can leave it empty. SQLite can't ALTER
    a column's nullability in place, but every SQLite database here is created fresh from
    the current (already-nullable) model definition, so there's nothing to relax there."""
    inspector = inspect(engine)
    if "ops_operational_cases" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("ops_operational_cases")}
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if "behavior_finding_id" not in existing_columns:
            connection.execute(text("ALTER TABLE ops_operational_cases ADD COLUMN behavior_finding_id INTEGER"))
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE ops_operational_cases ALTER COLUMN finding_id DROP NOT NULL"))

