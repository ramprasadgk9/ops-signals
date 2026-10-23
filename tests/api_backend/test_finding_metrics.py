"""Active findings on GET /api/metrics (backend/app/services/finding_metrics.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from backend.app.config import FindingMetricsConfig
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity, SignalEntity
from backend.app.services.finding_metrics import ActiveFindingsCollector, FindingCounts, count_active_findings

STRONG = [("pyod_outlier", "anomaly"), ("ruptures", "ruptures")]
MODERATE = [("ruptures", "ruptures")]
SPIKE = [("pyod_outlier", "anomaly")]


@pytest.fixture(autouse=True)
def no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # The collector is one per process; without this a scrape in one test would answer the next.
    monkeypatch.setenv("OPS_SIGNALS_FINDING_METRICS_CACHE_SECONDS", "0")
    monkeypatch.delenv("OPS_SIGNALS_FINDING_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("OPS_SIGNALS_FINDING_METRICS_MAX_SERIES", raising=False)


def _add_finding(
    db,
    finding_id: int,
    service: str | None,
    signals: list[tuple[str, str]],
    *,
    category: str = "behavior_change",
    metric: str = "http_latency",
    severity: str = "critical",
    cluster: str | None = None,
    problem_id: int | None = None,
    age: timedelta = timedelta(hours=1),
) -> None:
    created = datetime.now(timezone.utc) - age
    signal_ids = []
    for index, (analyzer, signal_type) in enumerate(signals):
        signal_id = f"sig-{finding_id}-{index}"
        signal_ids.append(signal_id)
        db.add(SignalEntity(signal_id=signal_id, signal_type=signal_type, analyzer_id=analyzer, metric_name=metric, service=service,
                            severity="high", start_time=created, end_time=created, evidence_json={}, importance_score=0.7,
                            analysis_run_id="run-1"))
    db.add(FindingEntity(id=finding_id, analysis_run_id="run-1", service=service, metric_name=metric, cluster=cluster,
                         title=f"finding {finding_id}", summary="s", category=category, health_status=severity,
                         importance_score=0.9, signal_ids=signal_ids, comparison_json={}, problem_id=problem_id,
                         created_at=created))


def _close_case(db, case_id: int, finding_id: int) -> None:
    now = datetime.now(timezone.utc)
    db.add(OperationalCaseEntity(id=case_id, finding_id=finding_id, analysis_run_id="run-1", case_title="c", case_status="resolved",
                                 finding_snapshot={}, investigation_status="done", investigation_notes=[], root_cause_status="unknown",
                                 root_cause_verified=False, outcome_status="resolved", memory_status="none",
                                 created_at=now, updated_at=now))


def _seed(*adds) -> None:
    with get_session_local()() as db:
        for add in adds:
            add(db)
        db.commit()


def _scrape(client: TestClient) -> dict[str, list]:
    response = client.get("/api/metrics")
    assert response.status_code == 200
    families = {family.name: family.samples for family in text_string_to_metric_families(response.text)}
    return families


def _active(families: dict[str, list]) -> dict[tuple[str, ...], float]:
    return {
        tuple(sample.labels[label] for label in ("service", "metric", "cluster", "evidence", "severity")): sample.value
        for sample in families["ops_signals_active_findings"]
    }


def test_active_findings_are_scraped_with_evidence_and_severity(client: TestClient) -> None:
    _seed(
        lambda db: _add_finding(db, 1, "checkout", STRONG, cluster="eu"),
        lambda db: _add_finding(db, 2, "payments", MODERATE, metric="error_rate", severity="significant"),
        lambda db: _add_finding(db, 3, "search", SPIKE, category="unusual_activity", severity="normal"),
        lambda db: _add_finding(db, 4, None, [("data_health", "data_gap")], category="data_quality", metric="queue_depth"),
    )

    families = _scrape(client)

    assert _active(families) == {
        ("checkout", "http_latency", "eu", "strong", "critical"): 1,
        ("payments", "error_rate", "", "moderate", "significant"): 1,
        ("search", "http_latency", "", "context", "normal"): 1,
        ("unknown", "queue_depth", "", "data_problem", "critical"): 1,
    }
    assert families["ops_signals_active_findings_up"][0].value == 1
    assert families["ops_signals_active_findings_dropped"][0].value == 0
    # The OTLP self-metrics are still on the same endpoint.
    assert "otlp_backlog_size" in families


def test_a_problem_seen_by_every_run_counts_once_as_its_newest_finding(client: TestClient) -> None:
    _seed(
        lambda db: _add_finding(db, 1, "checkout", MODERATE, age=timedelta(hours=3)),
        lambda db: _add_finding(db, 2, "checkout", STRONG, problem_id=1, age=timedelta(minutes=5)),
    )
    assert _active(_scrape(client)) == {("checkout", "http_latency", "", "strong", "critical"): 1}


def test_closed_cases_and_old_findings_stop_counting(client: TestClient) -> None:
    _seed(
        lambda db: _add_finding(db, 1, "checkout", STRONG),
        lambda db: _add_finding(db, 2, "checkout", STRONG, problem_id=1),
        lambda db: _close_case(db, 10, 1),
        lambda db: _add_finding(db, 3, "payments", STRONG, age=timedelta(hours=30)),
    )
    families = _scrape(client)
    assert _active(families) == {}
    assert families["ops_signals_active_findings_up"][0].value == 1


def test_series_cap_keeps_what_is_most_worth_alerting_on(db_session) -> None:
    for finding_id, service, signals, category in (
        (1, "a", SPIKE, "unusual_activity"),
        (2, "b", STRONG, "behavior_change"),
        (3, "c", MODERATE, "behavior_change"),
    ):
        _add_finding(db_session, finding_id, service, signals, category=category)
    db_session.commit()

    counts = count_active_findings(db_session, FindingMetricsConfig(max_series=1))

    assert list(counts.series) == [("b", "http_latency", "", "strong", "critical")]
    assert counts.dropped == 2


def test_database_outage_reports_up_0_instead_of_failing_the_scrape() -> None:
    def broken(_: FindingMetricsConfig) -> FindingCounts:
        raise RuntimeError("database is down")

    collector = ActiveFindingsCollector(load=broken, config=lambda: FindingMetricsConfig(cache_seconds=0))
    families = {family.name: family.samples for family in collector.collect()}

    assert families["ops_signals_active_findings"] == []
    assert families["ops_signals_active_findings_up"][0].value == 0


def test_scrapes_within_the_cache_window_reuse_the_last_count() -> None:
    calls: list[int] = []
    clock = [100.0]

    def load(_: FindingMetricsConfig) -> FindingCounts:
        calls.append(1)
        return FindingCounts(series={("a", "m", "", "strong", "critical"): len(calls)})

    collector = ActiveFindingsCollector(load=load, config=lambda: FindingMetricsConfig(cache_seconds=30), clock=lambda: clock[0])
    list(collector.collect())
    clock[0] += 10
    list(collector.collect())
    assert len(calls) == 1
    clock[0] += 30
    list(collector.collect())
    assert len(calls) == 2


def test_can_be_turned_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_FINDING_METRICS_ENABLED", "false")
    _seed(lambda db: _add_finding(db, 1, "checkout", STRONG))
    assert "ops_signals_active_findings" not in client.get("/api/metrics").text


def test_metrics_need_the_api_token_when_one_is_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Finding counts name services and metrics: not for anyone on the network without the token.
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "s3cret")
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200
