"""Storage behavior only real Postgres shows, so these run only when OPS_SIGNALS_TEST_DATABASE_URL
points at a disposable database. QA-28: concurrent runs rewriting the capability catalog hit
duplicate keys or deadlocks (SQLite has one writer at a time). QA-13: a missing label stored as the
text 'NaN' (SQLite turns NaN into NULL by itself). QA-30: saving an analysis failed on a database
the backend built from its models (Postgres rejects the NULL timestamps)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, select, text

from intelligence.storage.postgres_store import PostgresStore

DATABASE_URL = os.getenv("OPS_SIGNALS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set OPS_SIGNALS_TEST_DATABASE_URL to a disposable Postgres")

CAPABILITIES = [
    {"id": f"capability_{index}", "analyzer_id": f"analyzer_{index}", "title": "t", "description": "d", "supported_question_ids": ["q1", "q2"]}
    for index in range(12)
]


def _store() -> PostgresStore:
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with patch.object(PostgresStore, "_connection_string", return_value=DATABASE_URL):
        return PostgresStore(config)


def test_concurrent_runs_rewrite_the_catalog_without_failing() -> None:
    store = _store()
    store.metadata.create_all(store.engine, tables=[store.capabilities_table, store.capability_questions_table])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.save_capabilities(CAPABILITIES), range(40)))

    assert len(results) == 40
    with store.engine.begin() as connection:
        ids = sorted(row.id for row in connection.execute(select(store.capabilities_table)))
        links = connection.execute(select(store.capability_questions_table)).all()
    assert ids == sorted(capability["id"] for capability in CAPABILITIES)
    assert len(links) == 24


def test_missing_labels_are_stored_as_null_not_the_text_nan() -> None:
    store = _store()
    store.metadata.create_all(store.engine, tables=[store.normalized_table])
    points = pd.DataFrame(
        {
            "metric_name": ["cpu_usage"],
            "timestamp": [datetime(2026, 1, 1, tzinfo=timezone.utc)],
            "value": [1.0],
            "service": ["checkout"],
            "env": [float("nan")],
            "host": [float("nan")],
            "namespace": [float("nan")],
            "pod": [float("nan")],
            "source": ["generic"],
            "unit": [float("nan")],
            "metric_type": [float("nan")],
            "cluster": [float("nan")],
            "tags_json": [{}],
        }
    )

    store.save_normalized_points(points, analysis_run_id="qa13-run")

    with store.engine.begin() as connection:
        row = connection.execute(select(store.normalized_table).where(store.normalized_table.c.analysis_run_id == "qa13-run")).mappings().one()
    assert [row[column] for column in ("env", "host", "namespace", "pod", "unit", "metric_type", "cluster")] == [None] * 7
    assert (row["service"], row["source"]) == ("checkout", "generic")


def _points() -> pd.DataFrame:
    return pd.DataFrame(
        {"metric_name": ["cpu_usage"], "timestamp": [datetime(2026, 1, 1, tzinfo=timezone.utc)], "value": [1.0], "service": ["checkout"]}
    )


# No linked questions: the backend seeds the question catalog at startup, which this bare database skips.
LONE_CAPABILITY = [{"id": "capability_lone", "analyzer_id": "analyzer_lone", "title": "t", "description": "d", "supported_question_ids": []}]


def _reset_schema(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def backend_built_database():
    """A database created the way a Helm install's starts: the backend's models, no sql/init.sql.
    Emptied again afterwards, so the tests above still create their own tables."""
    from backend.app.models.entities import Base

    engine = create_engine(DATABASE_URL)
    _reset_schema(engine)
    Base.metadata.create_all(engine)
    yield engine
    _reset_schema(engine)
    engine.dispose()


def test_an_analysis_saves_on_a_database_the_backend_built(backend_built_database) -> None:
    store = _store()

    store.save_normalized_points(_points(), analysis_run_id="run-1")
    store.save_capabilities(LONE_CAPABILITY)

    with store.engine.begin() as connection:
        assert connection.execute(select(store.normalized_table.c.created_at)).scalar() is not None


def test_startup_adds_the_defaults_to_a_database_built_before_the_fix(backend_built_database) -> None:
    from backend.app.models.schema_compat import ensure_server_defaults

    with backend_built_database.begin() as connection:
        connection.execute(text("ALTER TABLE ops_normalized_timeseries_points ALTER COLUMN created_at DROP DEFAULT"))
        connection.execute(text("ALTER TABLE capabilities ALTER COLUMN updated_at DROP DEFAULT"))

    ensure_server_defaults(backend_built_database)
    ensure_server_defaults(backend_built_database)

    store = _store()
    store.save_normalized_points(_points(), analysis_run_id="run-1")
    store.save_capabilities(LONE_CAPABILITY)
