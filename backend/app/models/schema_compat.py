from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

ANALYSIS_RUN_COLUMN_SQL = {
    "router_version": "VARCHAR(100)",
    "feature_extractor_version": "VARCHAR(100)",
    "analyzer_registry_version": "VARCHAR(100)",
    "series_profile_json": "JSON",
    "router_decisions_json": "JSON",
    "executed_analyzers_json": "JSON",
    "generated_findings_json": "JSON",
    "connection_id": "VARCHAR(64)",
    "series_key": "VARCHAR(64)",
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
    "ops_operational_findings": {"ai_summary": "TEXT", "ai_wording": "JSON"},
    "ops_behavior_findings": {"ai_explanation": "TEXT"},
    "ops_operational_cases": {"writeup": "TEXT"},
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


# When a finding's problem happened and which earlier finding it repeats, so a problem that every
# run sees again is counted and alerted once (intelligence/storage/postgres_store.py).
_FINDING_PROBLEM_COLUMNS = {"event_start": "TIMESTAMPTZ", "event_end": "TIMESTAMPTZ", "ongoing": "BOOLEAN", "problem_id": "BIGINT"}


def ensure_finding_problem_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "ops_operational_findings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("ops_operational_findings")}
    missing = {name: ddl for name, ddl in _FINDING_PROBLEM_COLUMNS.items() if name not in existing}
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing.items():
            connection.execute(text(f"ALTER TABLE ops_operational_findings ADD COLUMN {name} {ddl}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_ops_finding_problem ON ops_operational_findings (problem_id)"))


_CLUSTER_TABLES = ("ops_normalized_timeseries_points", "ops_operational_signals", "ops_operational_findings", "ops_change_events")


def ensure_cluster_schema(engine: Engine) -> None:
    """Adds the nullable `cluster` column (the external label that tells apart the same series from
    different clusters behind one Mimir/Thanos endpoint) to points, signals and findings, and to change
    events so a deploy to one cluster isn't matched to another cluster's findings."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table_name in _CLUSTER_TABLES:
        if table_name not in existing_tables:
            continue
        if "cluster" in {column["name"] for column in inspector.get_columns(table_name)}:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN cluster TEXT"))


AUTONOMOUS_POLICY_SCHEDULING_COLUMN_SQL = {
    "schedule_minutes": "INTEGER",
    "next_run_at": "TIMESTAMPTZ",
    "last_run_status": "VARCHAR(32)",
    "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
    "connection_id": "VARCHAR(64) NOT NULL DEFAULT 'default'",
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
    columns = {column["name"]: column for column in inspector.get_columns("ops_operational_cases")}
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if "behavior_finding_id" not in columns:
            connection.execute(text("ALTER TABLE ops_operational_cases ADD COLUMN behavior_finding_id INTEGER"))
        # Only while it is still NOT NULL: the ALTER takes an exclusive lock even when there is
        # nothing to change (see ensure_case_import_schema).
        if dialect == "postgresql" and not columns.get("finding_id", {}).get("nullable", True):
            connection.execute(text("ALTER TABLE ops_operational_cases ALTER COLUMN finding_id DROP NOT NULL"))


def ensure_ticketing_schema(engine: Engine) -> None:
    """Ensures the 4 ticketing integration tables and their indexes exist in the target database.
    Called on app startup so existing deployed databases receive the schema without requiring
    manual migration execution."""
    from backend.app.models.entities import (
        Base,
        CaseTicketEventEntity,
        CaseTicketLinkEntity,
        TicketOperationEntity,
        TicketWebhookDeliveryEntity,
    )

    ticketing_tables = [
        TicketOperationEntity.__table__,
        CaseTicketLinkEntity.__table__,
        CaseTicketEventEntity.__table__,
        TicketWebhookDeliveryEntity.__table__,
    ]

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing = [t for t in ticketing_tables if t.name not in existing_tables]
    if missing:
        Base.metadata.create_all(bind=engine, tables=missing)


CASE_IMPORT_COLUMN_SQL = {
    "source": "VARCHAR(32) NOT NULL DEFAULT 'detected'",
    "source_id": "TEXT",
    "source_url": "TEXT",
    "import_batch_id": "VARCHAR(32)",
    "content_hash": "VARCHAR(64)",
}


def ensure_server_defaults(engine: Engine) -> None:
    """Adds the model's database defaults (server_default) to existing Postgres columns that lack
    them. The analysis pipeline inserts through its own table definitions without those values, so
    on a database the backend built from the models alone (Helm, no sql/init.sql) every save failed
    with "null value in column created_at". New databases get the defaults from create_all; SQLite
    can't add a default in place, and its databases here are created fresh."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy.sql.elements import ClauseElement

    from backend.app.models.entities import Base

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            current = {column["name"]: column.get("default") for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.server_default is None or column.name not in current or current[column.name] is not None:
                    continue
                arg = column.server_default.arg
                default = (
                    str(arg.compile(dialect=engine.dialect))
                    if isinstance(arg, ClauseElement)
                    else "'" + str(arg).replace("'", "''") + "'"
                )
                connection.execute(text(f'ALTER TABLE "{table.name}" ALTER COLUMN "{column.name}" SET DEFAULT {default}'))
                logger.info("Added database default %s to %s.%s", default, table.name, column.name)


_CASE_LINK_UNIQUE_INDEXES = {
    "idx_ops_case_finding": "finding_id",
    "idx_ops_case_behavior_finding": "behavior_finding_id",
}


def ensure_case_link_unique_schema(engine: Engine) -> None:
    """One case per finding and per behavior. Only sql/init.sql created the finding index, so a
    database built by the backend itself (Helm, SQLite) had neither, and two people opening a case
    for the same finding at once got two cases. A database that already holds such duplicates is
    left as it is, with a warning: picking which case to drop is the operator's call."""
    inspector = inspect(engine)
    if "ops_operational_cases" not in inspector.get_table_names():
        return
    existing = {index["name"] for index in inspector.get_indexes("ops_operational_cases")}
    for name, column in _CASE_LINK_UNIQUE_INDEXES.items():
        if name in existing:
            continue
        with engine.begin() as connection:
            duplicates = connection.execute(
                text(
                    f"SELECT {column} FROM ops_operational_cases WHERE {column} IS NOT NULL "
                    f"GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 5"
                )
            ).scalars().all()
            if duplicates:
                logger.warning(
                    "Not adding unique index %s: several cases share %s %s. Merge or delete the extra cases, then restart.",
                    name,
                    column,
                    ", ".join(str(value) for value in duplicates),
                )
                continue
            connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON ops_operational_cases ({column})"))


def ensure_case_import_schema(engine: Engine) -> None:
    """Lets a case be imported from an incident tool instead of opened from a finding
    (docs/importing-incident-history.md). Adds the provenance columns and the unique
    (source, source_id) index that makes re-imports update rather than duplicate, and on
    Postgres swaps the old exactly-one-finding check for one that also admits imported cases.
    The new check is added NOT VALID: it guards every new or updated row without rescanning
    existing ones, which predate it and were all written by the detected-case path.

    SQLite can't swap a CHECK constraint in place. SQLite databases here are created fresh from
    the current model, so only an old on-disk SQLite file keeps the stricter check - imports into
    it fail on insert and need a new database."""
    inspector = inspect(engine)
    if "ops_operational_cases" not in inspector.get_table_names():
        return
    from backend.app.models.entities import CASE_SOURCE_LINK_CHECK

    existing = {column["name"] for column in inspector.get_columns("ops_operational_cases")}
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for name, ddl in CASE_IMPORT_COLUMN_SQL.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE ops_operational_cases ADD COLUMN {name} {ddl}"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_case_source_record "
                "ON ops_operational_cases (source, source_id)"
            )
        )
        if dialect == "postgresql":
            # Only when the old check is still there: DROP ... IF EXISTS takes an exclusive lock on
            # the table even when there is nothing to drop, and two backends starting together (the
            # web UI and plugin dev stacks share one database) deadlocked on it.
            has_old_check = connection.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_case_exactly_one_source'")
            ).first()
            if has_old_check:
                connection.execute(
                    text("ALTER TABLE ops_operational_cases DROP CONSTRAINT IF EXISTS ck_case_exactly_one_source")
                )
            has_new_check = connection.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_case_source_link'")
            ).first()
            if not has_new_check:
                connection.execute(
                    text(
                        "ALTER TABLE ops_operational_cases ADD CONSTRAINT ck_case_source_link "
                        f"CHECK ({CASE_SOURCE_LINK_CHECK}) NOT VALID"
                    )
                )


_METRIC_USAGE_COLUMNS = {
    "metric_usage_snapshots": {"series_total": "INTEGER", "series_unwatched": "INTEGER", "unread_rules_json": "JSON NOT NULL DEFAULT '[]'"},
    "metric_usage_items": {
        "series": "INTEGER",
        "jobs_json": "JSON NOT NULL DEFAULT '{}'",
        "metric_type": "VARCHAR(32)",
        "recording_rule": "BOOLEAN NOT NULL DEFAULT FALSE",
        "first_seen": "TIMESTAMPTZ",
    },
}


def ensure_metric_usage_schema(engine: Engine) -> None:
    """Adds columns to metric usage tables created before they existed."""
    existing_tables = set(inspect(engine).get_table_names())
    for table_name, column_sql in _METRIC_USAGE_COLUMNS.items():
        if table_name in existing_tables:
            _add_missing_columns(engine, table_name, column_sql)


def _add_missing_columns(engine: Engine, table_name: str, column_sql: dict[str, str]) -> None:
    """Postgres DDL, with TIMESTAMPTZ and JSON rewritten for SQLite. IF NOT EXISTS on Postgres: the
    web UI and plugin dev backends share one database and start together."""
    existing_columns = {column["name"] for column in inspect(engine).get_columns(table_name)}
    missing = {name: ddl for name, ddl in column_sql.items() if name not in existing_columns}
    if not missing:
        return
    postgres = engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        for name, ddl in missing.items():
            if not postgres:
                ddl = ddl.replace("TIMESTAMPTZ", "DATETIME").replace("JSON ", "TEXT ")
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {'IF NOT EXISTS ' if postgres else ''}{name} {ddl}"))


def ensure_point_series_key_schema(engine: Engine) -> None:
    """Adds series_key to points tables created before it existed, with the index that finds a
    series' newest stored point (run_points.py)."""
    if "ops_normalized_timeseries_points" not in set(inspect(engine).get_table_names()):
        return
    _add_missing_columns(engine, "ops_normalized_timeseries_points", {"series_key": "VARCHAR(64)"})
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_ops_norm_series_ts ON ops_normalized_timeseries_points (series_key, timestamp)"))


def ensure_case_memory_schema(engine: Engine) -> None:
    """Adds memory_opted_out to cases tables created before it existed (memory/catch_up.py)."""
    inspector = inspect(engine)
    if "ops_operational_cases" not in inspector.get_table_names():
        return
    if "memory_opted_out" in {column["name"] for column in inspector.get_columns("ops_operational_cases")}:
        return
    false, true = ("FALSE", "TRUE") if engine.dialect.name == "postgresql" else ("0", "1")
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE ops_operational_cases ADD COLUMN memory_opted_out BOOLEAN NOT NULL DEFAULT {false}"))
        # Before this column, a case the user removed from memory and one an outage kept out were
        # both just not_indexed. Treat existing ones as removed, so catch-up never re-adds a case
        # someone took out; "Add to memory" still brings any of them back. Failed cases stay
        # eligible: a failure is never a user's choice.
        connection.execute(text(f"UPDATE ops_operational_cases SET memory_opted_out = {true} WHERE memory_status = 'not_indexed'"))


# Who did what (backend/app/identity.py): nullable, so older rows and requests that didn't come
# through Grafana simply have no name.
_ACTOR_COLUMNS = {
    "ops_finding_feedback": {"answered_by": "TEXT"},
    "ops_operational_cases": {"created_by": "TEXT", "resolved_by": "TEXT"},
    "autonomous_policies": {"created_by": "TEXT", "edited_by": "TEXT", "edited_at": "TIMESTAMPTZ"},
}


def ensure_actor_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    sqlite = engine.dialect.name == "sqlite"
    for table_name, column_sql in _ACTOR_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = {name: ddl for name, ddl in column_sql.items() if name not in existing_columns}
        if not missing:
            continue
        with engine.begin() as connection:
            for name, ddl in missing.items():
                if sqlite:
                    ddl = "DATETIME" if ddl == "TIMESTAMPTZ" else ddl
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))
                else:
                    # IF NOT EXISTS: two backends starting at once (replicas, or the two dev stacks) both
                    # see the column missing, and the second one's plain ADD failed its startup.
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {ddl}"))
