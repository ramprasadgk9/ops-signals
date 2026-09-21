from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import Integer

from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore


def _config(table_prefix: str = "ops_") -> SimpleNamespace:
    return SimpleNamespace(
        storage=SimpleNamespace(
            postgres=SimpleNamespace(
                host="unused",
                port=5432,
                database="unused",
                user="unused",
                password="unused",
                table_prefix=table_prefix,
            )
        )
    )


@pytest.fixture()
def store() -> Iterator[PostgresStore]:
    # PostgresStore declares its BIGINT primary keys using the postgres dialect's BIGINT
    # type, which relies on a real Postgres sequence for autoincrement. SQLite only
    # auto-generates rowids for a column typed exactly INTEGER, so swap in plain Integer
    # for this in-memory test engine only -- production always runs against real Postgres,
    # where the BIGINT type in postgres_store.py is untouched and correct.
    with (
        patch.object(PostgresStore, "_connection_string", return_value="sqlite:///:memory:"),
        patch("intelligence.storage.postgres_store.BIGINT", Integer),
    ):
        instance = PostgresStore(_config())
    instance.init_db()
    yield instance
    instance.engine.dispose()


def _signal(**overrides) -> OperationalSignal:
    payload = {
        "signal_type": "anomaly",
        "analyzer_id": "zscore",
        "metric_name": "cpu_usage",
        "service": "checkout-service",
        "env": "prod",
        "severity": "warning",
        "confidence": 0.8,
        "start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "end_time": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        "summary": "CPU spike detected",
    }
    payload.update(overrides)
    return OperationalSignal(**payload)


def _finding(**overrides) -> OperationalFinding:
    payload = {
        "service": "checkout-service",
        "metric_name": "cpu_usage",
        "title": "CPU baseline shift",
        "summary": "CPU usage shifted above baseline",
        "category": "baseline",
        "health_status": "degraded",
        "importance_score": 0.5,
        "investigation_priority": 2,
        "signal_ids": ["sig-1"],
        "comparison_json": {"percent_change": 10.0},
    }
    payload.update(overrides)
    return OperationalFinding(**payload)


def test_connection_string_uses_psycopg_driver() -> None:
    # create_engine() never opens a connection eagerly, so this exercises the real
    # _connection_string() against a real (unreachable) postgres config without a live DB.
    config = _config()
    config.storage.postgres.host = "db.internal"
    config.storage.postgres.port = 6543
    config.storage.postgres.database = "ops_signals"
    config.storage.postgres.user = "ops"
    config.storage.postgres.password = "secret"

    instance = PostgresStore(config)

    assert instance._connection_string() == "postgresql+psycopg://ops:secret@db.internal:6543/ops_signals"


def test_init_db_creates_all_tables(store: PostgresStore) -> None:
    from sqlalchemy import inspect

    table_names = set(inspect(store.engine).get_table_names())
    assert {
        "ops_normalized_timeseries_points",
        "ops_operational_signals",
        "ops_operational_findings",
        "capabilities",
        "question_catalog",
        "capability_questions",
        "analysis_runs",
        "question_answers",
    } <= table_names


def test_save_and_fetch_normalized_points(store: PostgresStore) -> None:
    dataframe = pd.DataFrame(
        {
            "metric_name": ["cpu_usage", "cpu_usage"],
            "timestamp": [datetime(2026, 1, 1), datetime(2026, 1, 1, 0, 1)],
            "value": [10.0, 12.5],
            "service": ["checkout-service", "checkout-service"],
        }
    )

    store.save_normalized_points(dataframe, analysis_run_id="run-1")

    fetched = store.fetch_normalized_points()
    assert len(fetched) == 2
    assert set(fetched["analysis_run_id"]) == {"run-1"}
    assert sorted(fetched["value"].tolist()) == [10.0, 12.5]


def test_save_signals_attaches_embeddings_by_index(store: PostgresStore) -> None:
    signals = [_signal(signal_id="sig-1"), _signal(signal_id="sig-2")]

    store.save_signals(signals, embeddings={0: [0.1, 0.2], 1: [0.3, 0.4]})

    fetched = store.fetch_signals()
    assert len(fetched) == 2
    by_id = {row["signal_id"]: row for _, row in fetched.iterrows()}
    assert by_id["sig-1"]["embedding_json"] == [0.1, 0.2]
    assert by_id["sig-2"]["embedding_json"] == [0.3, 0.4]


def test_save_signals_without_embeddings_leaves_embedding_json_null(store: PostgresStore) -> None:
    store.save_signals([_signal(signal_id="sig-1")])

    fetched = store.fetch_signals()
    assert fetched.iloc[0]["embedding_json"] is None


def test_save_signals_empty_list_is_a_no_op(store: PostgresStore) -> None:
    store.save_signals([])

    assert store.fetch_signals().empty


def test_fetch_signals_for_ids_filters_and_handles_empty_input(store: PostgresStore) -> None:
    store.save_signals([_signal(signal_id="sig-1"), _signal(signal_id="sig-2")])

    fetched = store.fetch_signals_for_ids(["sig-2"])
    assert fetched["signal_id"].tolist() == ["sig-2"]

    assert store.fetch_signals_for_ids([]).empty


def test_save_findings_empty_list_is_a_no_op(store: PostgresStore) -> None:
    store.save_findings([])

    assert store.fetch_findings().empty


def test_fetch_findings_orders_by_importance_score_desc(store: PostgresStore) -> None:
    store.save_findings(
        [
            _finding(title="low", importance_score=0.2),
            _finding(title="high", importance_score=0.9),
            _finding(title="mid", importance_score=0.5),
        ]
    )

    fetched = store.fetch_findings()
    assert fetched["title"].tolist() == ["high", "mid", "low"]


def test_save_capabilities_replaces_existing_rows_and_links_questions(store: PostgresStore) -> None:
    store.save_capabilities(
        [
            {
                "id": "cap-1",
                "analyzer_id": "zscore",
                "title": "Detect anomalies",
                "description": "...",
                "enabled": True,
                "supported_question_ids": ["q1", "q2"],
            }
        ]
    )
    store.save_capabilities(
        [
            {
                "id": "cap-2",
                "analyzer_id": "prophet",
                "title": "Forecast",
                "description": "...",
                "supported_question_ids": [],
            }
        ]
    )

    with store.engine.begin() as connection:
        from sqlalchemy import select

        capabilities = connection.execute(select(store.capabilities_table)).mappings().all()
        links = connection.execute(select(store.capability_questions_table)).mappings().all()

    assert [row["id"] for row in capabilities] == ["cap-2"]
    assert links == []


def test_save_capabilities_empty_list_is_a_no_op_and_preserves_existing_rows(store: PostgresStore) -> None:
    store.save_capabilities([{"id": "cap-1", "analyzer_id": "zscore", "title": "t", "description": "d"}])

    store.save_capabilities([])

    with store.engine.begin() as connection:
        from sqlalchemy import select

        capabilities = connection.execute(select(store.capabilities_table)).mappings().all()
    assert len(capabilities) == 1


def test_save_questions_inserts_then_upserts_on_conflict(store: PostgresStore) -> None:
    store.save_questions([{"id": "q1", "label": "Original", "description": "d", "display_order": 1}])
    store.save_questions([{"id": "q1", "label": "Updated", "description": "d2", "display_order": 2}])

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.question_catalog_table)).mappings().all()

    assert len(rows) == 1
    assert rows[0]["label"] == "Updated"
    assert rows[0]["display_order"] == 2


def test_save_questions_falls_back_to_plain_insert_on_unrecognized_dialect(store: PostgresStore) -> None:
    with patch.object(type(store.engine.dialect), "name", "mysql"):
        store.save_questions([{"id": "q1", "label": "Original", "description": "d", "display_order": 1}])

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.question_catalog_table)).mappings().all()

    assert [row["label"] for row in rows] == ["Original"]


def test_save_questions_empty_list_is_a_no_op(store: PostgresStore) -> None:
    store.save_questions([])

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.question_catalog_table)).mappings().all()
    assert rows == []


def test_create_analysis_run_filters_unknown_columns(store: PostgresStore) -> None:
    store.create_analysis_run(
        {
            "id": "run-1",
            "source_type": "csv",
            "provider": "generic",
            "service": "checkout-service",
            "metric_name": "cpu_usage",
            "start_time": datetime(2026, 1, 1),
            "end_time": datetime(2026, 1, 1, 1, 0),
            "sample_count": 100,
            "status": "running",
            "not_a_real_column": "should be dropped",
        }
    )

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.analysis_runs_table)).mappings().all()

    assert len(rows) == 1
    assert rows[0]["id"] == "run-1"
    assert rows[0]["status"] == "running"


def test_update_analysis_run_learning_snapshot_only_touches_allowed_fields(store: PostgresStore) -> None:
    store.create_analysis_run(
        {
            "id": "run-1",
            "source_type": "csv",
            "provider": "generic",
            "service": "checkout-service",
            "metric_name": "cpu_usage",
            "start_time": datetime(2026, 1, 1),
            "end_time": datetime(2026, 1, 1, 1, 0),
            "sample_count": 100,
            "status": "running",
        }
    )

    store.update_analysis_run_learning_snapshot(
        "run-1",
        {
            "status": "completed",
            "series_profile_json": {"sample_count": 100},
            "service": "should-be-ignored",
        },
    )

    with store.engine.begin() as connection:
        from sqlalchemy import select

        row = connection.execute(
            select(store.analysis_runs_table).where(store.analysis_runs_table.c.id == "run-1")
        ).mappings().one()

    assert row["status"] == "completed"
    assert row["series_profile_json"] == {"sample_count": 100}
    assert row["service"] == "checkout-service"


def test_update_analysis_run_learning_snapshot_no_allowed_fields_is_a_no_op(store: PostgresStore) -> None:
    store.create_analysis_run(
        {
            "id": "run-1",
            "source_type": "csv",
            "provider": "generic",
            "service": "checkout-service",
            "metric_name": "cpu_usage",
            "start_time": datetime(2026, 1, 1),
            "end_time": datetime(2026, 1, 1, 1, 0),
            "sample_count": 100,
            "status": "running",
        }
    )

    # Nothing raised, and nothing changes, when the payload has no allowed keys.
    store.update_analysis_run_learning_snapshot("run-1", {"not_allowed": "x"})

    with store.engine.begin() as connection:
        from sqlalchemy import select

        row = connection.execute(
            select(store.analysis_runs_table).where(store.analysis_runs_table.c.id == "run-1")
        ).mappings().one()
    assert row["status"] == "running"


def test_save_question_answers_empty_list_is_a_no_op(store: PostgresStore) -> None:
    store.save_question_answers([])

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.question_answers_table)).mappings().all()
    assert rows == []


def test_save_question_answers_persists_records(store: PostgresStore) -> None:
    store.save_question_answers(
        [
            {
                "analysis_run_id": "run-1",
                "question_id": "q1",
                "headline": "CPU is elevated",
                "answer": "CPU usage rose 40% over baseline.",
                "status": "answered",
                "priority": "high",
                "confidence": 0.75,
                "key_points_json": ["point-1"],
                "evidence_signal_ids": ["sig-1"],
            }
        ]
    )

    with store.engine.begin() as connection:
        from sqlalchemy import select

        rows = connection.execute(select(store.question_answers_table)).mappings().all()

    assert len(rows) == 1
    assert rows[0]["headline"] == "CPU is elevated"
    assert rows[0]["key_points_json"] == ["point-1"]
