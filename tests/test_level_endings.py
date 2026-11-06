"""A level change is over when its level comes back (issue #82, part C): latency 200 ms jumps to
1.8 s at 07:30 and a rollback brings it back at 11:30. The level change's checks run to the last
reading, so its findings always read as ongoing; after each run, the run's own readings decide
whether the level came back, came partly back or went high again (intelligence/level_endings.py)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import Integer, select
from sqlalchemy.orm import Session

from backend.app.models.entities import Base, FindingEntity
from backend.app.services import finding_trust as ft
from backend.app.services.finding_plain import finding_plain, utc_text
from intelligence.findings.schema import OperationalFinding
from intelligence.level_endings import ENDED, PARTLY_BACK, REOPENED, OpenLevelChange, level_event
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore

START = datetime(2026, 11, 6, 6, 0, tzinfo=timezone.utc)
JUMP = START + timedelta(hours=1, minutes=30)
BACK = START + timedelta(hours=5, minutes=30)
END = START + timedelta(hours=6)
METRIC = "http_request_duration_seconds"


def _points(levels: list[tuple[datetime, float]], end: datetime = END, metric: str = METRIC) -> pd.DataFrame:
    """Readings every 5 minutes from START to `end`, at the latest level that started by then."""
    rows = []
    moment = START
    while moment <= end:
        level = [value for since, value in levels if since <= moment][-1]
        wobble = 0.02 * level * (1 if (moment.minute // 5) % 2 else -1)
        rows.append({"timestamp": moment, "metric_name": metric, "service": "checkout-api", "value": level + wobble})
        moment += timedelta(minutes=5)
    return pd.DataFrame(rows)


def _problem(state: str | None = None) -> OpenLevelChange:
    return OpenLevelChange(problem_id=1, before=0.2, after=1.8, change_at=JUMP, state=state)


# --- The rule -------------------------------------------------------------------------------


def test_a_level_that_came_back_ended_when_the_stretch_back_began() -> None:
    event = level_event(_problem(), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))

    assert (event.kind, event.at) == (ENDED, BACK)
    assert event.level_during == pytest.approx(1.8, rel=0.03)
    assert event.level_now == pytest.approx(0.2, rel=0.03)
    # Already over: the next run adds nothing.
    assert level_event(_problem(ENDED), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)])) is None


def test_a_level_still_up_or_back_too_briefly_is_not_over() -> None:
    assert level_event(_problem(), _points([(START, 0.2), (JUMP, 1.8)])) is None
    # Back for 10 minutes: two readings, shorter than the 15 minutes it must last.
    assert level_event(_problem(), _points([(START, 0.2), (JUMP, 1.8), (END - timedelta(minutes=5), 0.2)])) is None


def test_a_level_only_partly_back_says_so_without_ending() -> None:
    event = level_event(_problem(), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.7)]))

    assert (event.kind, event.at) == (PARTLY_BACK, BACK)
    assert event.level_now == pytest.approx(0.7, rel=0.03)
    # All the way back later: it ends.
    assert level_event(_problem(PARTLY_BACK), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)])).kind == ENDED


def test_a_level_that_went_up_again_reopens() -> None:
    again = START + timedelta(hours=5)
    readings = _points([(START, 0.2), (JUMP, 1.8), (START + timedelta(hours=4), 0.2), (again, 1.8)])

    event = level_event(_problem(ENDED), readings)

    assert (event.kind, event.at) == (REOPENED, again)
    # Never over: high readings are just the problem going on.
    assert level_event(_problem(), readings) is None


def test_a_level_that_dropped_is_back_when_it_rises_again() -> None:
    dropped = OpenLevelChange(problem_id=1, before=500.0, after=100.0, change_at=JUMP)
    assert level_event(dropped, _points([(START, 500.0), (JUMP, 100.0), (BACK, 480.0)])).kind == ENDED


def test_missing_readings_at_the_end_are_no_proof_it_came_back() -> None:
    readings = _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)])
    readings.loc[readings.index[-1], "value"] = float("nan")
    assert level_event(_problem(), readings) is None


# --- Through the store and back to the card -------------------------------------------------


@pytest.fixture()
def store() -> Iterator[PostgresStore]:
    # As tests/test_finding_problems.py: SQLite only auto-generates INTEGER primary keys. The
    # backend's tables are made first, so the backend reads what the pipeline writes.
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with (
        patch.object(PostgresStore, "_connection_string", return_value="sqlite:///:memory:"),
        patch("intelligence.storage.postgres_store.BIGINT", Integer),
    ):
        instance = PostgresStore(config)
    Base.metadata.create_all(instance.engine)
    instance.init_db()
    yield instance
    instance.engine.dispose()


def _run(store: PostgresStore, run_id: str) -> str:
    store.create_analysis_run(
        {"id": run_id, "source_type": "prometheus", "service": "checkout-api", "metric_name": METRIC, "start_time": START,
         "end_time": END, "sample_count": 73, "status": "completed", "connection_id": "prod"}
    )
    return run_id


def _save_level_change(store: PostgresStore, run_id: str) -> None:
    """The finding the 07:35 run saves: latency rose at 07:30 and stayed higher."""
    signal = OperationalSignal(
        signal_type="ruptures", analyzer_id="ruptures", metric_name=METRIC, service="checkout-api", env=None, severity="high",
        confidence=0.9, start_time=START, end_time=JUMP + timedelta(minutes=5), summary="",
        evidence={"left_mean": 0.2, "right_mean": 1.8, "percent_change": 800.0, "change_point_time": JUMP.isoformat()},
        analysis_run_id=run_id,
    )
    store.save_signals([signal])
    store.save_findings([
        OperationalFinding(
            service="checkout-api", metric_name=METRIC, title=f"{METRIC} experienced a persistent baseline shift during the selected time window.",
            summary="", category="behavior_change", health_status="critical", importance_score=0.85, investigation_priority=1,
            signal_ids=[signal.signal_id], comparison_json={}, analysis_run_id=run_id,
            event_start=JUMP, event_end=JUMP + timedelta(minutes=5), ongoing=True,
        )
    ])


def _events(store: PostgresStore) -> list[tuple[int, str]]:
    table = store.problem_events_table
    with store.engine.begin() as connection:
        return [tuple(row) for row in connection.execute(select(table.c.problem_id, table.c.kind).order_by(table.c.id))]


def test_a_run_that_sees_the_level_back_saves_when_it_came_back(store: PostgresStore) -> None:
    _save_level_change(store, _run(store, "r1"))

    store.save_level_events(_run(store, "r2"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))
    store.save_level_events(_run(store, "r3"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))

    assert _events(store) == [(1, ENDED)]


def test_a_run_that_did_not_read_the_series_says_nothing_about_it(store: PostgresStore) -> None:
    _save_level_change(store, _run(store, "r1"))

    store.save_level_events(_run(store, "r2"), _points([(START, 0.5)], metric="process_cpu_seconds_total"))

    assert _events(store) == []


def test_a_level_change_that_came_back_reads_as_over_and_moves_to_context_an_hour_later(store: PostgresStore) -> None:
    _save_level_change(store, _run(store, "r1"))
    store.save_level_events(_run(store, "r2"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))

    with Session(store.engine) as db:
        rows = db.execute(select(FindingEntity)).scalars().all()
        within = ft.finding_trust(db, rows, now=BACK + timedelta(minutes=10))[1]
        later = ft.finding_trust(db, rows, now=BACK + timedelta(hours=1, minutes=5))[1]
        plain = finding_plain(db, rows)[1]

    assert (within["group"], within["tier"], within["badge"]) == ("level_change_single", "needs_attention", "moderate")
    assert within["ended_at"].startswith("2026-11-06T11:30")
    assert (later["tier"], later["badge"]) == ("context", "over")
    assert plain["headline"].endswith("rose sharply for 4 hours, then came back")
    assert utc_text(plain["what"]) == "About 200 ms until Nov 6, 07:30 UTC, then about 1.8 s. Back to about 199 ms since Nov 6, 11:30 UTC."


def test_a_level_partly_back_stays_in_needs_attention_and_says_where_it_is(store: PostgresStore) -> None:
    _save_level_change(store, _run(store, "r1"))
    store.save_level_events(_run(store, "r2"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.7)]))

    with Session(store.engine) as db:
        rows = db.execute(select(FindingEntity)).scalars().all()
        trust = ft.finding_trust(db, rows, now=END + timedelta(hours=3))[1]
        plain = finding_plain(db, rows)[1]

    assert (trust["tier"], trust["ended_at"]) == ("needs_attention", None)
    assert plain["headline"].endswith("rose sharply and stayed higher")
    assert utc_text(plain["what"]).endswith("Partly back: about 698 ms since Nov 6, 11:30 UTC.")


def test_a_level_that_went_up_again_needs_attention_again(store: PostgresStore) -> None:
    _save_level_change(store, _run(store, "r1"))
    store.save_level_events(_run(store, "r2"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))
    store.save_level_events(_run(store, "r3"), _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2), (END + timedelta(minutes=5), 1.8)], end=END + timedelta(minutes=30)))

    with Session(store.engine) as db:
        rows = db.execute(select(FindingEntity)).scalars().all()
        trust = ft.finding_trust(db, rows, now=END + timedelta(hours=3))[1]

    assert _events(store) == [(1, ENDED), (1, REOPENED)]
    assert (trust["tier"], trust["badge"], trust["ended_at"]) == ("needs_attention", "moderate", None)


def test_a_way_back_seen_as_a_change_of_its_own_still_counts_as_the_level_coming_back(store: PostgresStore) -> None:
    # A later run's strongest break is the way back ("dropped and stayed lower", 1.3 s -> 200 ms),
    # linked to the same problem: the jump's own levels still decide, and every finding says so.
    _save_level_change(store, _run(store, "r1"))
    run_id = _run(store, "r2")
    signal = OperationalSignal(
        signal_type="ruptures", analyzer_id="ruptures", metric_name=METRIC, service="checkout-api", env=None, severity="high",
        confidence=0.9, start_time=START, end_time=END, summary="",
        evidence={"left_mean": 1.3, "right_mean": 0.2, "percent_change": -84.0, "change_point_time": BACK.isoformat()},
        analysis_run_id=run_id,
    )
    store.save_signals([signal])
    store.save_findings([
        OperationalFinding(
            service="checkout-api", metric_name=METRIC, title=f"{METRIC} experienced a persistent baseline shift during the selected time window.",
            summary="", category="behavior_change", health_status="significant", importance_score=0.7, investigation_priority=2,
            signal_ids=[signal.signal_id], comparison_json={}, analysis_run_id=run_id, event_start=JUMP, event_end=END, ongoing=True,
        )
    ])
    store.save_level_events(run_id, _points([(START, 0.2), (JUMP, 1.8), (BACK, 0.2)]))

    with Session(store.engine) as db:
        rows = db.execute(select(FindingEntity).order_by(FindingEntity.id)).scalars().all()
        plain = finding_plain(db, rows)

    assert [row.problem_id for row in rows] == [None, 1]
    assert _events(store) == [(1, ENDED)]
    for finding_id in (1, 2):
        assert plain[finding_id]["badge"] == "worse"
        assert plain[finding_id]["headline"].endswith("rose sharply for 4 hours, then came back")
        assert utc_text(plain[finding_id]["what"]).startswith("About 200 ms until Nov 6, 07:30 UTC, then about 1.8 s.")
