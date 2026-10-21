from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.behavior_lab import router as lab_router
from backend.app.behavior_intelligence.history import judge_run, summarize
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.models.db import get_db
from backend.app.models.entities import AnalysisRunEntity, Base, NormalizedPoint, SignalEntity

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POOL = {definition.id: definition for definition in load_definitions(PROJECT_ROOT / "config" / "behavior_definitions.d")}["pool_exhaustion"]
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _change(metric: str, percent: float, start: datetime, end: datetime) -> dict:
    return {
        "metric_name": metric, "analyzer_id": "ruptures", "signal_type": "ruptures", "importance_score": 0.8,
        "start_time": start, "end_time": end, "evidence": {"percent_change": percent},
    }


def _both_rising(hours_ago: int) -> list[dict]:
    start, end = NOW - timedelta(hours=hours_ago + 2), NOW - timedelta(hours=hours_ago)
    return [_change("db_connection_wait_seconds", 80, start, end), _change("db_connections_active", 40, start, end)]


class TestJudgeRun:
    def test_a_matching_run(self) -> None:
        run = judge_run(POOL, "r1", NOW, _both_rising(1))
        assert run["matched"] is True
        assert run["blocked_by"] == [] and run["missing_inputs"] == []
        assert run["overlap_minutes"] == 120.0
        assert (run["start"], run["end"]) == (NOW - timedelta(hours=3), NOW - timedelta(hours=1))

    def test_an_input_without_signals_cannot_be_judged(self) -> None:
        run = judge_run(POOL, "r1", NOW, _both_rising(1)[:1])
        assert run["matched"] is False
        assert run["missing_inputs"] == ["db_pool"]
        assert run["conditions"] == []

    def test_the_condition_that_failed_is_named(self) -> None:
        start, end = NOW - timedelta(hours=2), NOW
        signals = [_change("db_connection_wait_seconds", 80, start, end), _change("db_connections_active", -40, start, end)]
        run = judge_run(POOL, "r1", NOW, signals)
        assert run["blocked_by"] == ["none of: db_pool.change.upward equals True"]

    def test_changes_at_different_times_fail_the_timing_check(self) -> None:
        signals = [
            _change("db_connection_wait_seconds", 80, NOW - timedelta(hours=8), NOW - timedelta(hours=7)),
            _change("db_connections_active", 40, NOW - timedelta(hours=2), NOW - timedelta(hours=1)),
        ]
        run = judge_run(POOL, "r1", NOW, signals)
        assert run["blocked_by"] == ["timing: the metrics did not change at the same time"]


class TestSummarize:
    def test_fired_when_any_run_matched(self) -> None:
        runs = [judge_run(POOL, "r2", NOW, _both_rising(1)), judge_run(POOL, "r1", NOW, _both_rising(5)[:1])]
        summary = summarize(POOL, runs)
        assert (summary["verdict"], summary["runs_checked"], summary["runs_judged"], summary["runs_matched"]) == ("fired", 2, 1, 1)
        assert summary["inputs"][1] == {"alias": "db_pool", "metric_name": "db_connections_active", "analyzers": ["trend", "baseline_shift", "ruptures"], "runs_with_signals": 1}
        assert [(item["fact"], item["passed_runs"]) for item in summary["conditions"]] == [("db_wait.change.upward", 1), ("db_pool.change.upward", 1)]

    def test_cant_check_names_the_input_that_never_had_signals(self) -> None:
        runs = [judge_run(POOL, f"r{i}", NOW, _both_rising(i)[:1]) for i in range(3)]
        summary = summarize(POOL, runs)
        assert (summary["verdict"], summary["reason"]) == ("cant_check", "no signals for db_pool")

    def test_never_gives_the_most_common_reason(self) -> None:
        start, end = NOW - timedelta(hours=2), NOW
        down = [_change("db_connection_wait_seconds", 80, start, end), _change("db_connections_active", -40, start, end)]
        runs = [judge_run(POOL, "r1", NOW, down), judge_run(POOL, "r2", NOW, down)]
        assert summarize(POOL, runs)["reason"] == "none of: db_pool.change.upward equals True"
        assert summarize(POOL, runs)["verdict"] == "never"

    def test_no_runs(self) -> None:
        assert summarize(POOL, [])["verdict"] == "no_runs"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SignalEntity.__table__, AnalysisRunEntity.__table__, NormalizedPoint.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _client(db: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(PROJECT_ROOT)
    app = FastAPI()
    app.include_router(lab_router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _draft() -> dict:
    return {
        "id": "pool_preview",
        "title": "Pool preview",
        "inputs": [
            {"alias": "db_wait", "metric_name": "db_connection_wait_seconds", "analyzers": ["trend", "baseline_shift", "ruptures"]},
            {"alias": "db_pool", "metric_name": "db_connections_active", "analyzers": ["trend", "baseline_shift", "ruptures"]},
        ],
        "conditions": {"all": [{"fact": "db_wait.change.upward", "operator": "equals", "value": True}, {"fact": "db_pool.change.upward", "operator": "equals", "value": True}]},
        "correlation": {"max_time_gap": "30m", "minimum_overlap": "5m"},
        "output": {"category": "saturation", "severity": "high", "title": "Pool preview", "summary": "x"},
    }


def _seed(db: Session) -> None:
    def signal(run: str, metric: str, percent: float, hours_ago: int, service: str = "checkout-api") -> SignalEntity:
        return SignalEntity(
            signal_id=f"{run}-{metric}", signal_type="ruptures", analyzer_id="ruptures", metric_name=metric, service=service,
            start_time=NOW - timedelta(hours=hours_ago + 2), end_time=NOW - timedelta(hours=hours_ago),
            evidence_json={"percent_change": percent}, importance_score=0.8, analysis_run_id=run,
        )

    db.add_all([
        # Newest: both rose together - fires.
        signal("run-new", "db_connection_wait_seconds", 90, 1), signal("run-new", "db_connections_active", 45, 1),
        # Older: only the wait time had a signal.
        signal("run-mid", "db_connection_wait_seconds", 60, 20),
        # Another service, and a run older than the look-back: both ignored.
        signal("run-other", "db_connection_wait_seconds", 90, 1, service="payments"),
        signal("run-old", "db_connection_wait_seconds", 90, 24 * 9),
        # A run with no signals on these metrics: only the runs table knows it.
        AnalysisRunEntity(id="run-quiet", source_type="csv", service="checkout-api", metric_name="db_connections_active",
                          start_time=NOW - timedelta(hours=50), end_time=NOW - timedelta(hours=48), sample_count=10, status="completed"),
    ])
    db.add_all([
        NormalizedPoint(metric_name="db_connection_wait_seconds", service="checkout-api", timestamp=NOW - timedelta(minutes=5 * i), value=float(i))
        for i in range(30)
    ])
    db.commit()


def test_the_endpoint_judges_each_recent_run_of_the_service(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(db)
    with _client(db, monkeypatch) as client:
        body = client.post("/api/behavior-definitions/history-preview", json={"definition": _draft(), "service": "checkout-api", "hours": 168}).json()

    assert body["verdict"] == "fired"
    assert [(run["analysis_run_id"], run["matched"], run["missing_inputs"]) for run in body["runs"]] == [
        ("run-new", True, []),
        ("run-mid", False, ["db_pool"]),
        ("run-quiet", False, ["db_wait", "db_pool"]),
    ]
    assert (body["runs_checked"], body["runs_judged"], body["runs_matched"]) == (3, 1, 1)
    wait_series = body["series"][0]
    assert wait_series["metric_name"] == "db_connection_wait_seconds"
    assert 0 < len(wait_series["points"]) <= 240
    assert body["series"][1]["points"] == []
    assert body["series_truncated"] is False


def test_the_look_back_limits_the_runs(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(db)
    with _client(db, monkeypatch) as client:
        body = client.post("/api/behavior-definitions/history-preview", json={"definition": _draft(), "service": "checkout-api", "hours": 6}).json()
    assert [run["analysis_run_id"] for run in body["runs"]] == ["run-new"]


def test_an_invalid_definition_is_refused(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = _draft()
    draft["conditions"] = {"all": [{"fact": "db_wait.not_a_fact", "operator": "equals", "value": True}]}
    with _client(db, monkeypatch) as client:
        response = client.post("/api/behavior-definitions/history-preview", json={"definition": draft, "service": "checkout-api"})
    assert response.status_code == 400
    assert "not a known fact" in response.json()["detail"]


def test_history_services_come_from_the_runs_table_newest_first(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(db)
    db.add(AnalysisRunEntity(id="run-pay", source_type="csv", service="payments", metric_name="m",
                             start_time=NOW - timedelta(hours=3), end_time=NOW - timedelta(hours=2), sample_count=1, status="completed"))
    db.commit()
    with _client(db, monkeypatch) as client:
        assert client.get("/api/behavior-definitions/history-services").json() == ["payments", "checkout-api"]
