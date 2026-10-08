"""The metric usage check end to end against the fixture dashboards (the same ones
scripts/seed_metric_usage_dashboards.py loads into a local Grafana), with Grafana and Prometheus
faked at the HTTP-client boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from fastapi.testclient import TestClient

from backend.app.config import MetricUsageConfig, PrometheusConnectionConfig
from backend.app.integrations.grafana.client import GrafanaError
from backend.app.metric_usage import service
from backend.app.metric_usage.service import check_is_due, run_check
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, MetricUsageItemEntity, MetricUsageSnapshotEntity

FIXTURES = Path(__file__).parents[1] / "fixtures" / "grafana_metric_usage"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
PROMETHEUS_METRICS = [
    "request_latency_p95", "error_rate", "cpu_usage", "up", "ops_signal_lab_value", "ops_signals_test_cpu_usage",
    "prometheus_http_request_duration_seconds_bucket", "prometheus_tsdb_head_samples_appended_total",
    "prometheus_tsdb_head_series", "go_goroutines",
]


class FakeGrafana:
    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.dashboards = {item["dashboard"]["uid"]: item for item in (json.loads(path.read_text()) for path in (FIXTURES / "dashboards").glob("*.json"))}

    def datasource_types(self) -> dict[str, str]:
        raise GrafanaError("Grafana refused /api/datasources (403): check the token's role", 403)

    def folder_titles(self) -> dict[str, str]:
        if self.down:
            raise GrafanaError("Grafana connection failed: Connection refused")
        return {item["meta"]["folderUid"]: item["meta"]["folderTitle"] for item in self.dashboards.values()}

    def list_dashboards(self) -> list[dict]:
        return [{"uid": uid, "title": item["dashboard"]["title"], "folderTitle": item["meta"]["folderTitle"]} for uid, item in self.dashboards.items()]

    def get_dashboard(self, uid: str) -> dict:
        return self.dashboards[uid]

    def alert_rules(self) -> list[dict]:
        return json.loads((FIXTURES / "alert_rules.json").read_text())

    def library_panel(self, uid: str) -> dict:
        return {}


class FakePrometheus:
    def __init__(self, names: list[str], *, rules_error: bool = False, series: dict[str, int] | None = None) -> None:
        self.config = PrometheusConnectionConfig(name="Local Prometheus", base_url="http://prom:9090")
        self.names = names
        self.rules_error = rules_error
        self.series = series

    def series_counts_by_name(self) -> dict[str, int]:
        if self.series is None:
            raise HTTPException(status_code=422, detail="query too expensive")
        return self.series

    def label_values(self, label: str, **_: object) -> list[str]:
        assert label == "__name__"
        return self.names

    def rules(self) -> dict:
        if self.rules_error:
            raise HTTPException(status_code=404, detail="ruler not enabled")
        return {"status": "success", "data": {"groups": []}}


def _config(**overrides: object) -> MetricUsageConfig:
    return MetricUsageConfig(**{"enabled": True, "exclude_folders": ["Scratch"], "ignore_metrics": ["go_*"], **overrides})


def _finding(metric: str, health: str = "significant", hours_ago: float = 1) -> FindingEntity:
    return FindingEntity(
        service="checkout", metric_name=metric, title=f"{metric} changed", summary="changed", category="unusual_activity",
        health_status=health, importance_score=0.7, investigation_priority=2, signal_ids=[], comparison_json={},
        created_at=NOW - timedelta(hours=hours_ago),
    )


@pytest.fixture()
def app_client(client: TestClient) -> TestClient:
    return client


def _run(db, *, grafana=None, prometheus=None, config=None, now=NOW) -> MetricUsageSnapshotEntity:
    snapshot = run_check(
        db, config or _config(), grafana=grafana if grafana is not None else FakeGrafana(),
        prometheus=prometheus or {"default": FakePrometheus(PROMETHEUS_METRICS)}, trigger="manual", now=now,
    )
    db.refresh(snapshot)
    db.expunge(snapshot)  # readable after the session closes
    return snapshot


def test_check_sorts_fixture_metrics_into_groups(app_client: TestClient) -> None:
    with get_session_local()() as db:
        db.add_all([_finding("ops_signals_test_cpu_usage"), _finding("ops_signals_test_cpu_usage", "critical"), _finding("error_rate"), _finding("up", "normal")])
        db.commit()
        snapshot = _run(db)
        statuses = {item.metric_name: item.status for item in db.query(MetricUsageItemEntity).all()}

    assert snapshot.status == "completed"
    assert statuses == {
        # Its only dashboard is in the excluded Scratch folder, and it had two problems.
        "ops_signals_test_cpu_usage": "blind_spot",
        "request_latency_p95": "watched",
        "error_rate": "watched",
        "cpu_usage": "watched",  # through the $metric variable on Lab Signals
        "up": "watched",  # alert rule only
        "ops_signal_lab_value": "watched",
        "prometheus_http_request_duration_seconds_bucket": "watched",
        "prometheus_tsdb_head_samples_appended_total": "watched",
        "prometheus_tsdb_head_series": "watched",
    }  # go_goroutines is ignored
    assert (snapshot.metrics_total, snapshot.watched, snapshot.blind_spots, snapshot.unwatched, snapshot.missing) == (9, 8, 1, 0, 0)
    assert snapshot.sources_json["grafana"]["dashboards_excluded"] == ["Scratch / Old test board"]
    assert snapshot.sources_json["grafana"]["dashboards_read"] == 2
    assert any("datasources" in warning for warning in snapshot.sources_json["warnings"])

    body = app_client.get("/api/metric-usage").json()
    assert body["snapshot"]["watched_percent"] == pytest.approx(88.9)
    first = body["items"][0]
    assert (first["metric"], first["status"], first["problem_findings"], first["analyzed"]) == ("ops_signals_test_cpu_usage", "blind_spot", 2, True)

    error_rate = app_client.get("/api/metric-usage/metrics", params={"name": ["error_rate", "nope"]}).json()
    assert set(error_rate) == {"error_rate"}
    assert {usage["location"] for usage in error_rate["error_rate"]["usages"]} == {
        "Production / API Health / Error rate",
        "Production / Checkout error rate high",
    }

    blind_only = app_client.get("/api/metric-usage", params={"status": "blind_spot"}).json()
    assert [item["metric"] for item in blind_only["items"]] == ["ops_signals_test_cpu_usage"]
    assert blind_only["items_total"] == 1


def test_dashboard_metric_missing_from_prometheus_is_reported(app_client: TestClient) -> None:
    with get_session_local()() as db:
        _run(db, prometheus={"default": FakePrometheus([name for name in PROMETHEUS_METRICS if name != "request_latency_p95"])})
    item = app_client.get("/api/metric-usage/metrics", params={"name": "request_latency_p95"}).json()["request_latency_p95"]
    assert item["status"] == "missing"
    assert item["connections"] == []


def test_old_and_normal_findings_are_not_problems(app_client: TestClient) -> None:
    with get_session_local()() as db:
        db.add_all([_finding("ops_signals_test_cpu_usage", hours_ago=30), _finding("ops_signals_test_cpu_usage", "normal")])
        db.commit()
        snapshot = _run(db)
    assert snapshot.blind_spots == 0
    assert snapshot.unwatched == 1


def test_grafana_down_fails_the_check_and_keeps_the_last_good_snapshot(app_client: TestClient) -> None:
    with get_session_local()() as db:
        good = _run(db, now=NOW - timedelta(hours=6))
        failed = _run(db, grafana=FakeGrafana(down=True))
    assert failed.status == "failed"
    assert "Connection refused" in failed.error

    body = app_client.get("/api/metric-usage").json()
    assert body["snapshot"]["id"] == good.id
    assert body["last_failure"]["id"] == failed.id
    assert body["items_total"] == 9


def test_prometheus_rules_error_is_a_warning_not_a_failure(app_client: TestClient) -> None:
    with get_session_local()() as db:
        snapshot = _run(db, prometheus={"default": FakePrometheus(PROMETHEUS_METRICS, rules_error=True)})
    assert snapshot.status == "completed"
    assert any("ruler not enabled" in warning for warning in snapshot.sources_json["warnings"])


def test_check_without_grafana_still_reads_prometheus(app_client: TestClient) -> None:
    with get_session_local()() as db:
        snapshot = run_check(db, _config(), grafana=None, prometheus={"default": FakePrometheus(["a", "b"])}, trigger="manual", now=NOW)
        db.refresh(snapshot)
    assert (snapshot.status, snapshot.metrics_total, snapshot.unwatched) == ("completed", 2, 2)
    assert snapshot.sources_json["grafana"] == {"configured": False}


def test_check_is_due_after_the_interval(app_client: TestClient) -> None:
    with get_session_local()() as db:
        assert check_is_due(db, _config(enabled=False), NOW) is False
        assert check_is_due(db, _config(), NOW) is True
        _run(db, now=NOW)
        assert check_is_due(db, _config(), NOW + timedelta(hours=5)) is False
        assert check_is_due(db, _config(), NOW + timedelta(hours=6)) is True


def test_old_snapshots_are_pruned(app_client: TestClient) -> None:
    with get_session_local()() as db:
        for hours in range(4):
            _run(db, config=_config(keep_snapshots=2), now=NOW + timedelta(hours=hours))
        snapshots = db.query(MetricUsageSnapshotEntity).all()
        remaining_items = {item.snapshot_id for item in db.query(MetricUsageItemEntity).all()}
    assert len(snapshots) == 2
    assert remaining_items == {snapshot.id for snapshot in snapshots}


def test_a_second_check_while_one_runs_is_refused(app_client: TestClient) -> None:
    service._running.acquire()
    try:
        response = app_client.post("/api/metric-usage/run")
    finally:
        service._running.release()
    assert response.status_code == 409


def test_grafana_status_when_not_configured(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_GRAFANA_URL", raising=False)
    body = app_client.get("/api/metric-usage/grafana/status").json()
    assert body["configured"] is False
    assert body["reachable"] is False


def test_snapshot_is_saved_before_its_items_when_foreign_keys_are_enforced(app_client: TestClient) -> None:
    """Postgres enforces metric_usage_items.snapshot_id; SQLite only with this pragma."""
    with get_session_local()() as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        snapshot = _run(db)
        assert db.query(MetricUsageItemEntity).filter_by(snapshot_id=snapshot.id).count() == 9
    assert snapshot.status == "completed"


SERIES = {name: 10 for name in PROMETHEUS_METRICS} | {"ops_signals_test_cpu_usage": 4000, "go_goroutines": 5}


def test_series_counts_are_stored_and_priced_only_when_a_rate_is_set(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with get_session_local()() as db:
        snapshot = _run(db, prometheus={"default": FakePrometheus(PROMETHEUS_METRICS, series=SERIES)})
    # go_goroutines is ignored, so its 5 series aren't counted anywhere.
    assert (snapshot.series_total, snapshot.series_unwatched) == (4080, 4000)

    monkeypatch.delenv("OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES", raising=False)
    body = app_client.get("/api/metric-usage").json()
    assert (body["snapshot"]["series_total"], body["snapshot"]["series_unwatched"]) == (4080, 4000)
    assert body["cost"] is None
    assert next(item for item in body["items"] if item["metric"] == "ops_signals_test_cpu_usage")["series"] == 4000

    monkeypatch.setenv("OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES", "2.5")
    monkeypatch.setenv("OPS_SIGNALS_METRIC_USAGE_CURRENCY", "EUR")
    cost = app_client.get("/api/metric-usage").json()["cost"]
    assert cost == {"per_1k_series_month": 2.5, "currency": "EUR", "unwatched_monthly": 10.0, "total_monthly": 10.2}


def test_series_count_failure_is_a_warning_and_leaves_cost_unknown(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES", "2.5")
    with get_session_local()() as db:
        snapshot = _run(db)
    assert snapshot.status == "completed"
    assert snapshot.series_total is None
    assert any("series" in warning and "query too expensive" in warning for warning in snapshot.sources_json["warnings"])
    cost = app_client.get("/api/metric-usage").json()["cost"]
    assert cost == {"per_1k_series_month": 2.5, "currency": "USD", "unwatched_monthly": None, "total_monthly": None}


def test_series_columns_are_added_to_tables_created_before_them() -> None:
    from sqlalchemy import create_engine, inspect

    from backend.app.models.schema_compat import ensure_metric_usage_schema

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE metric_usage_snapshots (id TEXT PRIMARY KEY, missing INTEGER)"))
        connection.execute(text("CREATE TABLE metric_usage_items (id INTEGER PRIMARY KEY, analyzed BOOLEAN)"))
    ensure_metric_usage_schema(engine)
    ensure_metric_usage_schema(engine)  # a second startup changes nothing
    columns = {table: {column["name"] for column in inspect(engine).get_columns(table)} for table in ("metric_usage_snapshots", "metric_usage_items")}
    assert {"series_total", "series_unwatched"} <= columns["metric_usage_snapshots"]
    assert "series" in columns["metric_usage_items"]
