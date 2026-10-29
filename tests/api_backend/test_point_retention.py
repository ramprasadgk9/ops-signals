"""Stored points older than the retention period are deleted, except those behind a finding that has
a case (point_retention.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, NormalizedPoint, OperationalCaseEntity
from backend.app.services import point_retention
from backend.app.services.point_retention import delete_old_points

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
NOW = START + timedelta(days=60)


@pytest.fixture()
def db(tmp_path):
    with TestClient(create_app(f"sqlite+pysqlite:///{tmp_path / 'retention.db'}")):
        with get_session_local()() as session:
            yield session


def _points(db, *, day: int, hours: int = 24, run_id: str | None = None, key: str | None = None, metric: str = "cpu_usage") -> None:
    """One point an hour for `hours`, starting `day` days after START."""
    first = START + timedelta(days=day)
    db.add_all(
        NormalizedPoint(
            metric_name=metric, service="checkout", timestamp=first + timedelta(hours=hour), value=float(hour),
            analysis_run_id=run_id, series_key=key,
        )
        for hour in range(hours)
    )
    db.commit()


def _run(db, run_id: str, *, day: int, key: str | None = None) -> None:
    """A run over the 24 hours from `day`, as AnalysisMetricExecutor records it."""
    db.add(
        AnalysisRunEntity(
            id=run_id, source_type="prometheus", service="checkout", metric_name="cpu_usage",
            start_time=START + timedelta(days=day), end_time=START + timedelta(days=day, hours=23),
            sample_count=24, status="completed", series_key=key,
        )
    )
    db.commit()


def _case_for(db, run_id: str) -> int:
    finding = FindingEntity(
        analysis_run_id=run_id, service="checkout", metric_name="cpu_usage", title="CPU went up",
        summary="CPU went up", category="change", health_status="critical",
    )
    db.add(finding)
    db.commit()
    db.add(OperationalCaseEntity(finding_id=finding.id, analysis_run_id=run_id, case_title="CPU incident", finding_snapshot={}))
    db.commit()
    return finding.id


def _count(db, **where) -> int:
    query = select(func.count(NormalizedPoint.id))
    for column, value in where.items():
        query = query.where(getattr(NormalizedPoint, column) == value)
    return db.execute(query).scalar()


def test_points_older_than_the_retention_period_are_deleted(db) -> None:
    _points(db, day=0, run_id="old")
    _points(db, day=45, run_id="recent")
    _points(db, day=0, metric="csv_upload")  # no run id, like old CSV points

    deleted, more_left = delete_old_points(db, days=30, now=NOW)

    assert (deleted, more_left) == (48, False)
    assert _count(db, analysis_run_id="old") == 0
    assert _count(db, metric_name="csv_upload") == 0
    assert _count(db, analysis_run_id="recent") == 24


def test_points_behind_a_case_are_kept_at_any_age(db) -> None:
    _points(db, day=0, run_id="incident")
    _points(db, day=1, run_id="noise")
    _points(db, day=1, metric="csv_upload")
    finding_id = _case_for(db, "incident")

    delete_old_points(db, days=30, now=NOW)

    assert _count(db, analysis_run_id="incident") == 24
    assert _count(db, analysis_run_id="noise") == 0
    # Not kept by a case just because it has no run id to compare.
    assert _count(db, metric_name="csv_upload") == 0
    # The finding itself is never touched.
    assert db.get(FindingEntity, finding_id) is not None


def test_a_case_keeps_the_series_points_in_its_runs_window_whoever_saved_them(db) -> None:
    # Stored by series: the case's run saved only its last 12 hours; an earlier run saved the rest
    # of its window (run_points.py). Points outside that window go.
    _points(db, day=0, hours=36, run_id="earlier", key="cpu")
    _points(db, day=1, hours=12, run_id="incident", key="cpu")
    _run(db, "earlier", day=0, key="cpu")
    _run(db, "incident", day=1, key="cpu")
    _case_for(db, "incident")

    delete_old_points(db, days=30, now=NOW)

    window = select(func.count(NormalizedPoint.id)).where(
        NormalizedPoint.series_key == "cpu",
        NormalizedPoint.timestamp >= START + timedelta(days=1),
        NormalizedPoint.timestamp <= START + timedelta(days=1, hours=23),
    )
    assert db.execute(window).scalar() == 12 + 12
    assert _count(db, series_key="cpu") == 12 + 12


def test_zero_days_keeps_every_point(db) -> None:
    _points(db, day=0, run_id="old")

    assert delete_old_points(db, days=0, now=NOW) == (0, False)
    assert _count(db, analysis_run_id="old") == 24


def test_a_large_backlog_is_deleted_over_several_runs(db) -> None:
    _points(db, day=0, run_id="old")

    assert delete_old_points(db, days=30, now=NOW, batch_size=5, max_deleted=10) == (10, True)
    assert delete_old_points(db, days=30, now=NOW, batch_size=5, max_deleted=100) == (14, False)
    assert _count(db, analysis_run_id="old") == 0


def test_the_scheduler_runs_it_once_an_hour_unless_a_backlog_is_left(monkeypatch) -> None:
    calls = []
    results = iter([(10, True), (3, False), (0, False)])

    def fake_delete(db, *, days):
        calls.append(days)
        return next(results)

    monkeypatch.setattr(point_retention, "delete_old_points", fake_delete)
    monkeypatch.setattr(point_retention, "_last_started", None)
    monkeypatch.setattr("backend.app.models.db.get_session_local", lambda: lambda: _NullSession())
    monkeypatch.setenv("OPS_SIGNALS_POINT_RETENTION_DAYS", "7")

    point_retention.run_if_due()  # backlog left: due again next tick
    point_retention.run_if_due()  # done: not due for an hour
    point_retention.run_if_due()
    assert calls == [7, 7]

    monkeypatch.setattr(point_retention, "_last_started", None)
    monkeypatch.setenv("OPS_SIGNALS_POINT_RETENTION_DAYS", "0")
    point_retention.run_if_due()
    assert calls == [7, 7]


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
