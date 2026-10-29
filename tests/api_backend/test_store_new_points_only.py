"""A scheduled run analyzes its whole window again each time but saves only the points newer than
its series' last stored point; a run's chart still shows its whole window (run_points.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
from backend.app.main import create_app
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint
from backend.app.services.run_points import series_key
from intelligence.config import load_config
from intelligence.storage.postgres_store import PostgresStore

START = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
CPU = series_key("prom", 'avg by (service) (cpu_usage{service="checkout"})')


@pytest.fixture()
def api(tmp_path):
    """The backend and the analysis store on one SQLite file, as they share Postgres in production."""
    url = f"sqlite+pysqlite:///{tmp_path / 'points.db'}"
    app = create_app(url)
    with TestClient(app) as client:
        config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
        with patch.object(PostgresStore, "_connection_string", return_value=url):
            store = PostgresStore(config)
        yield client, store
        store.engine.dispose()


def _run(store: PostgresStore, monkeypatch, *, from_minute: int, minutes: int = 1440, key: str | None = CPU) -> str:
    """One analysis run over [START + from_minute, + minutes], one point a minute, analyzers stubbed."""
    executor = MetricAnalysisExecutor(load_config("config.yaml"), store=store)
    monkeypatch.setattr(executor, "_route_analyzers", lambda frame: ([], {}, "test"))
    monkeypatch.setattr(executor, "_build_analyzers", lambda routing: [])
    monkeypatch.setattr(executor, "_evaluate_behavior_intelligence", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_counts", lambda *args, **kwargs: (0, 0, 0))
    stamps = [START + timedelta(minutes=from_minute + index) for index in range(minutes + 1)]
    points = pd.DataFrame(
        {"timestamp": stamps, "metric_name": "cpu_usage", "service": "checkout", "source": "prometheus", "value": [float(index) for index in range(len(stamps))]}
    )
    return executor.execute_normalized(points, run_metadata={"connection_id": "prom"}, db=object(), series_key=key).analysis_run_id


def _stored(**where) -> int:
    with get_session_local()() as db:
        query = select(func.count(NormalizedPoint.id))
        for column, value in where.items():
            query = query.where(getattr(NormalizedPoint, column) == value)
        return db.execute(query).scalar()


def _chart(client: TestClient, run_id: str) -> list[dict]:
    response = client.get("/api/timeseries", params={"service": "checkout", "metric_name": "cpu_usage", "analysis_run_id": run_id})
    assert response.status_code == 200
    return response.json()


def test_a_later_run_saves_only_the_points_after_the_series_last_one(api, monkeypatch) -> None:
    _, store = api
    _run(store, monkeypatch, from_minute=0)
    second = _run(store, monkeypatch, from_minute=30)

    # 24h a minute apart, then only the 30 minutes the second run added - not a second 24h copy.
    assert _stored(series_key=CPU) == 1441 + 30
    assert _stored(analysis_run_id=second) == 30


def test_a_run_that_adds_nothing_new_saves_nothing(api, monkeypatch) -> None:
    _, store = api
    _run(store, monkeypatch, from_minute=0)
    again = _run(store, monkeypatch, from_minute=0)

    assert _stored(series_key=CPU) == 1441
    assert _stored(analysis_run_id=again) == 0


def test_each_runs_chart_still_shows_its_whole_window(api, monkeypatch) -> None:
    client, store = api
    first = _run(store, monkeypatch, from_minute=0)
    second = _run(store, monkeypatch, from_minute=30)

    for run_id, from_minute in ((first, 0), (second, 30)):
        chart = _chart(client, run_id)
        assert len(chart) == 1441
        assert pd.Timestamp(chart[0]["timestamp"]).tz_localize(None) == pd.Timestamp(START + timedelta(minutes=from_minute)).tz_localize(None)
        assert pd.Timestamp(chart[-1]["timestamp"]).tz_localize(None) == pd.Timestamp(START + timedelta(minutes=from_minute + 1440)).tz_localize(None)


def test_another_connection_keeps_its_own_copy_of_the_same_metric(api, monkeypatch) -> None:
    # Two Mimir tenants can have the same service and metric names; one's points must not stand in
    # for the other's.
    _, store = api
    other = series_key("mimir-b", 'avg by (service) (cpu_usage{service="checkout"})')
    _run(store, monkeypatch, from_minute=0)
    _run(store, monkeypatch, from_minute=0, key=other)

    assert _stored(series_key=CPU) == 1441
    assert _stored(series_key=other) == 1441


def test_runs_without_a_series_key_keep_their_own_points(api, monkeypatch) -> None:
    # CSV and OTLP runs, and runs stored before series keys, are still read by run id.
    client, store = api
    _run(store, monkeypatch, from_minute=0)
    own_copy = _run(store, monkeypatch, from_minute=30, minutes=60, key=None)

    assert _stored(analysis_run_id=own_copy) == 61
    assert len(_chart(client, own_copy)) == 61


def test_a_runs_stored_sample_covers_its_whole_window(api, monkeypatch) -> None:
    _, store = api
    _run(store, monkeypatch, from_minute=0)
    second = _run(store, monkeypatch, from_minute=30)

    with get_session_local()() as db:
        sample = MetricAnalyzerRecommendationService().find_sample(db, "checkout", "cpu_usage", second)
        latest = MetricAnalyzerRecommendationService().find_sample(db, "checkout", "cpu_usage")

    assert sample["sample_count"] == 1441
    assert latest["analysis_run_id"] == second
    assert latest["sample_count"] == 1441
