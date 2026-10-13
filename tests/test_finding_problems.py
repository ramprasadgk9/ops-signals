"""One problem, counted and alerted once: a finding that repeats a problem an earlier run already
reported is linked to it (problem_id) instead of standing as a new one. Scheduled Prometheus or
Mimir runs and OTLP cycles re-analyze a window that overlaps the last one, so each run used to
report the same problem again."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import Integer, select

from intelligence.finding_aggregator import FindingAggregator
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore, register_findings_hook

NINE = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
TITLE = "memory.usage experienced a persistent baseline shift during the selected time window."


@pytest.fixture()
def store() -> Iterator[PostgresStore]:
    # As tests/test_postgres_store.py: SQLite only auto-generates INTEGER primary keys.
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with (
        patch.object(PostgresStore, "_connection_string", return_value="sqlite:///:memory:"),
        patch("intelligence.storage.postgres_store.BIGINT", Integer),
    ):
        instance = PostgresStore(config)
    instance.init_db()
    yield instance
    instance.engine.dispose()


@pytest.fixture()
def alerts() -> Iterator[list[OperationalFinding]]:
    received: list[OperationalFinding] = []
    register_findings_hook(received.extend)
    yield received
    register_findings_hook(None)


def _run(store: PostgresStore, run_id: str, connection_id: str | None = None) -> str:
    store.create_analysis_run(
        {
            "id": run_id,
            "source_type": "prometheus" if connection_id else "otel",
            "service": "postgres",
            "metric_name": "memory.usage",
            "start_time": NINE - timedelta(hours=6),
            "end_time": NINE + timedelta(hours=6),
            "sample_count": 100,
            "status": "completed",
            "connection_id": connection_id,
        }
    )
    return run_id


def _finding(run_id: str, start: datetime, end: datetime, *, cluster: str | None = None, health: str = "significant", title: str = TITLE) -> OperationalFinding:
    return OperationalFinding(
        service="postgres",
        metric_name="memory.usage",
        title=title,
        summary="",
        category="behavior_change",
        health_status=health,
        importance_score=0.6,
        investigation_priority=2,
        signal_ids=[],
        comparison_json={},
        analysis_run_id=run_id,
        cluster=cluster,
        event_start=start,
        event_end=end,
    )


def _saved(store: PostgresStore) -> list[tuple[int, int | None]]:
    table = store.findings_table
    with store.engine.begin() as connection:
        return [tuple(row) for row in connection.execute(select(table.c.id, table.c.problem_id).order_by(table.c.id))]


def test_the_same_problem_seen_by_later_runs_is_linked_to_the_first(store, alerts) -> None:
    # The user's example: memory jumps at 9:00 and stays high until a restart at 9:45; the runs
    # at 9:10, 9:20 (dating the start two minutes earlier, with more data) and 9:50 all see it.
    store.save_findings([_finding(_run(store, "r1"), NINE, NINE + timedelta(minutes=10))])
    store.save_findings([_finding(_run(store, "r2"), NINE - timedelta(minutes=2), NINE + timedelta(minutes=20))])
    store.save_findings([_finding(_run(store, "r3"), NINE, NINE + timedelta(minutes=45))])

    assert _saved(store) == [(1, None), (2, 1), (3, 1)]
    assert len(alerts) == 1


def test_the_same_kind_of_problem_at_another_time_is_a_new_problem(store, alerts) -> None:
    store.save_findings([_finding(_run(store, "r1"), NINE, NINE + timedelta(minutes=45))])
    store.save_findings([_finding(_run(store, "r2"), NINE + timedelta(hours=5), NINE + timedelta(hours=5, minutes=10))])

    assert _saved(store) == [(1, None), (2, None)]
    assert len(alerts) == 2


def test_a_problem_that_gets_worse_alerts_again(store, alerts) -> None:
    store.save_findings([_finding(_run(store, "r1"), NINE, NINE + timedelta(minutes=10))])
    store.save_findings([_finding(_run(store, "r2"), NINE, NINE + timedelta(minutes=20), health="significant")])
    store.save_findings([_finding(_run(store, "r3"), NINE, NINE + timedelta(minutes=30), health="critical")])

    assert _saved(store) == [(1, None), (2, 1), (3, 1)]
    assert [finding.health_status for finding in alerts] == ["significant", "critical"]


def test_plain_prometheus_without_clusters_links_repeats_too(store, alerts) -> None:
    store.save_findings([_finding(_run(store, "r1", connection_id="default"), NINE, NINE + timedelta(minutes=10))])
    store.save_findings([_finding(_run(store, "r2", connection_id="default"), NINE, NINE + timedelta(minutes=20))])

    assert _saved(store) == [(1, None), (2, 1)]
    assert len(alerts) == 1


def test_mimir_clusters_behind_one_endpoint_are_separate_problems(store, alerts) -> None:
    run = _run(store, "r1", connection_id="team-a")
    store.save_findings([_finding(run, NINE, NINE + timedelta(minutes=10), cluster="eu-a")])
    store.save_findings([_finding(_run(store, "r2", connection_id="team-a"), NINE, NINE + timedelta(minutes=10), cluster="us")])
    store.save_findings([_finding(_run(store, "r3", connection_id="team-a"), NINE, NINE + timedelta(minutes=20), cluster="eu-a")])

    assert _saved(store) == [(1, None), (2, None), (3, 1)]


def test_mimir_tenants_with_the_same_series_are_separate_problems(store, alerts) -> None:
    store.save_findings([_finding(_run(store, "r1", connection_id="team-a"), NINE, NINE + timedelta(minutes=10))])
    store.save_findings([_finding(_run(store, "r2", connection_id="team-b"), NINE, NINE + timedelta(minutes=10))])

    assert _saved(store) == [(1, None), (2, None)]


def test_a_different_kind_of_problem_on_the_same_series_is_a_new_problem(store, alerts) -> None:
    store.save_findings([_finding(_run(store, "r1"), NINE, NINE + timedelta(minutes=10))])
    store.save_findings([_finding(_run(store, "r2"), NINE, NINE + timedelta(minutes=10), title="memory.usage is trending in one direction.")])

    assert _saved(store) == [(1, None), (2, None)]


def test_a_finding_without_event_times_is_never_linked(store, alerts) -> None:
    run = _run(store, "r1")
    store.save_findings([OperationalFinding(service="postgres", metric_name="memory.usage", title=TITLE, analysis_run_id=run)])
    store.save_findings([OperationalFinding(service="postgres", metric_name="memory.usage", title=TITLE, analysis_run_id=run)])

    assert _saved(store) == [(1, None), (2, None)]


def _signal(start: datetime, end: datetime) -> OperationalSignal:
    return OperationalSignal(
        signal_type="baseline_shift",
        analyzer_id="baseline_shift",
        metric_name="memory.usage",
        service="postgres",
        env=None,
        severity="medium",
        confidence=0.9,
        start_time=start,
        end_time=end,
        summary="",
    )


def _points(last: datetime) -> pd.DataFrame:
    timestamps = pd.date_range(last - timedelta(hours=1), last, freq="15s")
    return pd.DataFrame({"timestamp": timestamps, "value": 1.0, "metric_name": "memory.usage", "service": "postgres"})


def test_a_finding_is_dated_by_its_most_recent_event_and_knows_if_it_is_still_going() -> None:
    last = NINE + timedelta(hours=5, minutes=10)
    old_spike = _signal(NINE, NINE + timedelta(minutes=2))
    new_jump = _signal(NINE + timedelta(hours=5), last)

    start, end, ongoing = FindingAggregator._event_time([old_spike, new_jump], _points(last))
    over_start, over_end, over = FindingAggregator._event_time([old_spike], _points(last))

    assert (start, end, ongoing) == (new_jump.start_time, last, True)
    assert (over_start, over_end, over) == (NINE, NINE + timedelta(minutes=2), False)


def test_scheduled_and_one_off_prometheus_runs_record_their_connection(monkeypatch) -> None:
    # Without it every Mimir tenant's run looked the same, so team-a's and team-b's findings on the
    # same series could be taken for one problem.
    from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
    from intelligence.config import load_config

    created: list[dict] = []

    class _Store:
        engine = None

        def create_analysis_run(self, payload):
            created.append(payload)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    executor = MetricAnalysisExecutor(load_config("config.yaml"), store=_Store())
    monkeypatch.setattr(executor, "_route_analyzers", lambda frame: ([], {}, "test"))
    monkeypatch.setattr(executor, "_build_analyzers", lambda routing: [])
    monkeypatch.setattr(executor, "_evaluate_behavior_intelligence", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_counts", lambda *args, **kwargs: (0, 0, 0))
    points = pd.DataFrame({"timestamp": [NINE], "metric_name": "memory.usage", "service": "postgres", "value": 1.0})

    executor.execute_normalized(points, run_metadata={"connection_id": "team-b"}, db=object())

    assert created[0]["connection_id"] == "team-b"
