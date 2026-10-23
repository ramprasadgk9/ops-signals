"""The metric usage check end to end against the fixture dashboards (the same ones
scripts/seed_metric_usage_dashboards.py loads into a local Grafana), with Grafana and Prometheus
faked at the HTTP-client boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
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
    def __init__(self, *, down: bool = False, datasources: list[dict] | None = None) -> None:
        self.down = down
        self._datasources = datasources
        self.dashboards = {item["dashboard"]["uid"]: item for item in (json.loads(path.read_text()) for path in (FIXTURES / "dashboards").glob("*.json"))}

    def datasources(self) -> list[dict]:
        if self._datasources is None:
            raise GrafanaError("Grafana refused /api/datasources (403): check the token's role", 403)
        return self._datasources

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
    def __init__(self, names: list[str], *, rules_error: bool = False, series: dict[str, int | dict[str, int]] | None = None, config: PrometheusConnectionConfig | None = None,
                 types: dict[str, str] | None = None, rule_groups: list[dict] | None = None) -> None:
        self.config = config or PrometheusConnectionConfig(name="Local Prometheus", base_url="http://prom:9090")
        self.names = names
        self.rules_error = rules_error
        self.series = series
        self.types = types or {}
        self.rule_groups = rule_groups or []

    def series_counts_by_job(self) -> dict[str, dict[str, int]]:
        if self.series is None:
            raise HTTPException(status_code=422, detail="query too expensive")
        return {name: (count if isinstance(count, dict) else {"node": count}) for name, count in self.series.items()}

    def metric_types(self) -> dict[str, str]:
        return self.types

    def label_values(self, label: str, **_: object) -> list[str]:
        assert label == "__name__"
        return self.names

    def rules(self) -> dict:
        if self.rules_error:
            raise HTTPException(status_code=404, detail="ruler not enabled")
        return {"status": "success", "data": {"groups": self.rule_groups}}


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
    assert {"series_total", "series_unwatched", "unread_rules_json"} <= columns["metric_usage_snapshots"]
    assert {"series", "jobs_json", "metric_type", "recording_rule", "first_seen"} <= columns["metric_usage_items"]


# The fixture dashboards read Grafana's "ops-signals-prometheus" datasource: the local Prometheus,
# as Grafana in Docker reaches it.
LOCAL_PROMETHEUS_DATASOURCE = {"uid": "ops-signals-prometheus", "name": "Prometheus", "type": "prometheus", "url": "http://prometheus:9090", "isDefault": True}


def _tenants(team_b_datasources: list[str] | None = None) -> dict[str, FakePrometheus]:
    url = "http://localhost:9009/prometheus"
    return {
        "team-a": FakePrometheus(["http_requests_total", "up"], config=PrometheusConnectionConfig(id="team-a", name="Mimir team-a", base_url=url)),
        "team-b": FakePrometheus(
            ["error_rate", "up"],
            config=PrometheusConnectionConfig(id="team-b", name="Mimir team-b", base_url=url, grafana_datasources=team_b_datasources or []),
        ),
    }


def test_dashboards_on_a_datasource_no_connection_reads_are_left_out_not_missing(app_client: TestClient) -> None:
    with get_session_local()() as db:
        snapshot = _run(db, grafana=FakeGrafana(datasources=[LOCAL_PROMETHEUS_DATASOURCE]), prometheus=_tenants())
        statuses = {item.metric_name: item.status for item in db.query(MetricUsageItemEntity).all()}

    assert snapshot.missing == 0
    assert set(statuses.values()) == {"unwatched"}
    assert any("Prometheus" in warning and "grafana_datasources" in warning for warning in snapshot.sources_json["warnings"])


def test_a_datasource_named_in_the_connections_file_is_read_on_that_tenant(app_client: TestClient) -> None:
    with get_session_local()() as db:
        _run(db, grafana=FakeGrafana(datasources=[LOCAL_PROMETHEUS_DATASOURCE]), prometheus=_tenants(["ops-signals-prometheus"]))
        items = {item.metric_name: item for item in db.query(MetricUsageItemEntity).all()}

    assert items["error_rate"].status == "watched"
    assert items["error_rate"].connections_json == ["team-b"]
    # Only team-a has it; the team-b dashboards can't show it.
    assert items["http_requests_total"].status == "unwatched"
    # Read by team-b panels, and team-b doesn't have it.
    assert items["request_latency_p95"].status == "missing"


UNUSED = ["orders_cache_evictions_total", "checkout_latency_seconds_bucket", "instance:cpu:avg", "scrape_duration_seconds"]


def _unused_prometheus(names: list[str] = UNUSED) -> dict[str, FakePrometheus]:
    return {"default": FakePrometheus(
        names,
        series={"orders_cache_evictions_total": {"orders": 8240}, "checkout_latency_seconds_bucket": {"checkout": 5000, "": 10}, "instance:cpu:avg": {"": 240}, "scrape_duration_seconds": {"orders": 3}},
        types={"checkout_latency_seconds": "histogram"},
        rule_groups=[{"name": "node", "rules": [{"type": "recording", "name": "instance:cpu:avg", "query": "avg by (instance) (rate(node_cpu_seconds_total[5m]))"}]}],
    )}


def test_unused_metrics_say_whether_drop_is_offered(app_client: TestClient) -> None:
    with get_session_local()() as db:
        db.add(_finding("checkout_latency_seconds_bucket", "normal"))  # analyzed, no problem
        db.commit()
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus=_unused_prometheus())

    body = app_client.get("/api/metric-usage", params={"status": ["unwatched"]}).json()
    items = {item["metric"]: item for item in body["items"]}
    evictions = items["orders_cache_evictions_total"]
    assert (evictions["jobs"], evictions["metric_type"], evictions["first_seen"], evictions["drop_blocked"]) == ({"default": {"orders": 8240}}, "counter", None, None)
    latency = items["checkout_latency_seconds_bucket"]
    assert (latency["metric_type"], latency["drop_blocked"], latency["series"]) == ("histogram", None, 5010)
    assert latency["drop_warnings"][0].startswith("10 of its 5,010 series have no job label")
    assert latency["drop_warnings"][1] == "Ops Signals analyzes this metric. Dropping it stops that analysis."
    assert items["instance:cpu:avg"]["recording_rule"] is True
    assert "recording rule" in items["instance:cpu:avg"]["drop_blocked"]
    assert "Prometheus makes it" in items["scrape_duration_seconds"]["drop_blocked"]
    assert body["unread_rules"] == [{
        "name": "instance:cpu:avg", "groups": ["node"], "connections": ["default"], "reads": ["node_cpu_seconds_total"],
        "feeds": [], "series": 240, "analyzed": False, "warnings": [],
    }]

    config = app_client.post("/api/metric-usage/drop-config", json={"metrics": ["orders_cache_evictions_total", "checkout_latency_seconds_bucket", "scrape_duration_seconds", "nope"]}).json()
    assert config["metrics"] == ["orders_cache_evictions_total", "checkout_latency_seconds_bucket"]
    assert config["series"] == 8240 + 5000  # not the 10 series without a job label
    assert [item["metric"] for item in config["skipped"]] == ["scrape_duration_seconds", "nope"]
    assert config["skipped"][1]["reason"] == "The latest check didn't list it."
    assert config["warnings"][1] == "checkout_latency_seconds_bucket: Ops Signals analyzes this metric. Dropping it stops that analysis."
    [block] = config["blocks"]
    assert block["connection"] == "default"
    jobs = {job["job_name"]: job["metric_relabel_configs"][0]["regex"] for job in yaml.safe_load(block["yaml"])["scrape_configs"]}
    assert jobs == {"checkout": "checkout_latency_seconds_bucket", "orders": "orders_cache_evictions_total"}


def test_metrics_new_since_the_last_check_wait_before_drop_is_offered(app_client: TestClient) -> None:
    # The API judges "new" against the real clock.
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=6)
    with get_session_local()() as db:
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus=_unused_prometheus(), now=now - timedelta(days=1))
        prometheus = _unused_prometheus(UNUSED + ["inventory_sync_lag_seconds"])
        prometheus["default"].series["inventory_sync_lag_seconds"] = {"inventory": 40}
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus=prometheus, now=now)
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus=prometheus, now=now + timedelta(hours=6))

    items = {item["metric"]: item for item in app_client.get("/api/metric-usage", params={"status": ["unwatched"]}).json()["items"]}
    # There before the first check: not new.
    assert items["orders_cache_evictions_total"]["first_seen"] is None
    # First listed by the second check, and that date is kept by the third.
    assert items["inventory_sync_lag_seconds"]["first_seen"].startswith(now.isoformat()[:19])
    assert items["inventory_sync_lag_seconds"]["drop_blocked"].startswith("First seen today. Drop is offered in 7 days")


def test_drop_config_needs_a_completed_check_and_some_metrics(app_client: TestClient) -> None:
    assert app_client.post("/api/metric-usage/drop-config", json={"metrics": ["a"]}).status_code == 409
    assert app_client.post("/api/metric-usage/drop-config", json={"metrics": []}).status_code == 422


def test_viewers_may_build_drop_config_but_not_run_checks() -> None:
    from backend.app.roles import required_role

    assert required_role("POST", "/api/metric-usage/drop-config") is None
    assert required_role("POST", "/api/metric-usage/run") == "Admin"


def test_first_seen_survives_a_check_where_the_connection_failed(app_client: TestClient) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=12)
    names = ["orders_cache_evictions_total"]
    other = PrometheusConnectionConfig(id="b", name="B", base_url="http://b:9090")

    class Down(FakePrometheus):
        def label_values(self, label: str, **_: object) -> list[str]:
            raise HTTPException(status_code=503, detail="Prometheus connection failed")

    with get_session_local()() as db:
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus={"b": FakePrometheus(names, config=other), "a": FakePrometheus(["x_total"])}, now=now - timedelta(days=1))
        snapshot = _run(db, grafana=FakeGrafana(datasources=[]), prometheus={"b": Down(names, config=other), "a": FakePrometheus(["x_total"])}, now=now)
        assert snapshot.status == "completed"
        _run(db, grafana=FakeGrafana(datasources=[]), prometheus={"b": FakePrometheus(names, config=other), "a": FakePrometheus(["x_total"])}, now=now + timedelta(hours=6))
        latest = db.query(MetricUsageItemEntity).filter_by(snapshot_id=service.latest_snapshot(db).id, metric_name="orders_cache_evictions_total").one()
    # There before the first check, so still not new after the check that couldn't list it.
    assert latest.first_seen is None


def test_a_metric_that_only_existed_as_missing_is_new_when_it_appears(app_client: TestClient) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=12)
    with get_session_local()() as db:
        # The fixture dashboards read request_latency_p95; this Prometheus doesn't have it yet.
        _run(db, prometheus={"default": FakePrometheus(["up"])}, now=now - timedelta(days=1))
        _run(db, prometheus={"default": FakePrometheus(["up", "request_latency_p95"])}, now=now)
        rows = {item.metric_name: item for item in db.query(MetricUsageItemEntity).filter_by(snapshot_id=service.latest_snapshot(db).id).all()}
    assert rows["request_latency_p95"].first_seen is not None
    assert rows["up"].first_seen is None


def test_unread_rules_warn_when_a_name_pattern_reads_them(app_client: TestClient) -> None:
    prometheus = _unused_prometheus()
    with get_session_local()() as db:
        snapshot = _run(db, grafana=FakeGrafana(datasources=[]), prometheus=prometheus)
        row = db.get(MetricUsageSnapshotEntity, snapshot.id)
        row.sources_json = {**row.sources_json, "name_patterns": [{"pattern": "instance:.*", "location": "Ops / Nodes / CPU"}]}
        db.commit()
    [rule] = app_client.get("/api/metric-usage").json()["unread_rules"]
    assert rule["warnings"] == ["A query reads metrics by a name pattern that matches it: Ops / Nodes / CPU. Check it before removing."]


def test_checks_from_before_per_job_counts_leave_jobs_unknown(app_client: TestClient) -> None:
    with get_session_local()() as db:
        snapshot = _run(db, grafana=FakeGrafana(datasources=[]), prometheus=_unused_prometheus())
        item = db.query(MetricUsageItemEntity).filter_by(snapshot_id=snapshot.id, metric_name="orders_cache_evictions_total").one()
        item.jobs_json = {"default": ["orders"]}
        db.commit()
    body = app_client.get("/api/metric-usage/metrics", params={"name": ["orders_cache_evictions_total"]}).json()
    assert body["orders_cache_evictions_total"]["jobs"] == {}
    assert "scrape job" in body["orders_cache_evictions_total"]["drop_blocked"]
