"""Named Prometheus connections (one per Mimir tenant): every request goes to the connection it
names, with that connection's URL and tenant header; unknown ids are a 404, never a silent fallback;
the legacy single-connection env still works as `default`. Only urlopen is faked, so the real
request building runs."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.api import ingestion_status
from backend.app.api.alerts import get_alert_enrichment_service
from backend.app.autonomous.repository import AutonomousPolicyRepository
from backend.app.autonomous.scheduler import _run_due_policies_once
from backend.app.config import (
    AlertEnrichmentConfig,
    PrometheusConnectionConfig,
    PrometheusConnections,
    PrometheusConnectionsError,
    get_alert_enrichment_config,
    get_prometheus_config,
    get_prometheus_connections,
)
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, AnalysisRunEntity, FindingEntity
from backend.app.services import prometheus_service

from tests.api_backend.test_alert_receiver_api import METRIC_KEY, NOW, STARTS_AT, FakePipeline, FakeQueryService, _payload

CONNECTIONS_YAML = """
default: mimir-a
connections:
  - id: mimir-a
    name: Mimir team A
    base_url: http://mimir-a.test/prometheus
    headers:
      X-Scope-OrgID: team-a
    match_labels:
      tenant: team-a
  - id: mimir-b
    name: Mimir team B
    base_url: http://mimir-b.test/prometheus
    bearer_token: ${TEAM_B_TOKEN}
    headers:
      X-Scope-OrgID: team-b
    match_labels:
      tenant: team-b
    cluster_label: k8s_cluster
    replica_labels: [replica]
"""


class FakeBackend:
    """Records each request (URL and headers) and answers every path with an empty success."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None, context=None):
        parts = urlsplit(request.full_url)
        self.requests.append(
            {
                "host": parts.netloc,
                "path": parts.path,
                "params": dict(parse_qsl(parts.query)),
                "headers": {key.lower(): value for key, value in request.header_items()},
            }
        )
        if parts.path.endswith("/query_range"):
            body = {"status": "success", "data": {"resultType": "matrix", "result": []}}
        elif parts.path.endswith("/buildinfo"):
            body = {"status": "success", "data": {"version": "2.9.0"}}
        else:
            body = {"status": "success", "data": []}
        return io.BytesIO(json.dumps(body).encode("utf-8"))


@pytest.fixture()
def connections_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "connections.yaml"
    path.write_text(CONNECTIONS_YAML)
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", str(path))
    monkeypatch.setenv("TEAM_B_TOKEN", "b-secret")
    monkeypatch.delenv("OPS_SIGNALS_PROMETHEUS_URL", raising=False)
    return path


@pytest.fixture()
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    fake = FakeBackend()
    monkeypatch.setattr(prometheus_service, "urlopen", fake)
    return fake


@pytest.fixture()
def api(connections_file, backend):
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        yield client


# --- config ----------------------------------------------------------------------------------


def test_legacy_env_gives_one_default_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_HEADERS", "X-Scope-OrgID:solo")

    connections = get_prometheus_connections()

    assert [c.id for c in connections.connections] == ["default"]
    assert connections.default.base_url == "http://prometheus:9090"
    assert connections.default.headers == {"X-Scope-OrgID": "solo"}
    assert connections.get("default") == get_prometheus_config()


def test_file_lists_connections_and_expands_secret_refs(connections_file) -> None:
    connections = get_prometheus_connections()

    assert [c.id for c in connections.connections] == ["mimir-a", "mimir-b"]
    assert connections.default.id == "mimir-a"
    b = connections.get("mimir-b")
    assert b is not None
    assert b.bearer_token == "b-secret"
    assert b.headers == {"X-Scope-OrgID": "team-b"}
    assert b.cluster_label == "k8s_cluster"
    assert b.replica_labels == ["replica"]
    # Unset per-connection fields keep the usual defaults.
    assert connections.get("mimir-a").cluster_label == "cluster"


def test_literal_default_id_aliases_the_default_connection(connections_file) -> None:
    connections = get_prometheus_connections()

    assert connections.get("default").id == "mimir-a"
    assert connections.get(None).id == "mimir-a"
    assert connections.get("nope") is None


def test_default_falls_back_to_the_first_connection(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"connections": [{"id": "x", "base_url": "http://x"}, {"id": "y", "base_url": "http://y"}]}))
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", str(path))

    assert get_prometheus_connections().default.id == "x"


@pytest.mark.parametrize(
    "content, message",
    [
        ("connections:\n  - {id: a, base_url: 'http://a'}\n  - {id: a, base_url: 'http://b'}\n", "duplicate"),
        ("connections:\n  - {id: a, base_url: 'http://a', bearer_token: '${NOT_SET_ANYWHERE}'}\n", "NOT_SET_ANYWHERE"),
        ("default: zzz\nconnections:\n  - {id: a, base_url: 'http://a'}\n", "zzz"),
        ("connections: []\n", "at least one"),
    ],
)
def test_bad_connections_file_fails_with_a_clear_error(tmp_path, monkeypatch: pytest.MonkeyPatch, content: str, message: str) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(content)
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", str(path))
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)

    with pytest.raises(PrometheusConnectionsError, match=message):
        get_prometheus_connections()


def test_bad_connections_file_stops_startup(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("connections: []\n")
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", str(path))

    with pytest.raises(PrometheusConnectionsError):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")):
            pass


def test_route_matches_alert_labels_then_falls_back_to_default(connections_file) -> None:
    connections = get_prometheus_connections()

    assert connections.route({"tenant": "team-b", "service": "x"}).id == "mimir-b"
    assert connections.route({"tenant": "team-a"}).id == "mimir-a"
    assert connections.route({"service": "x"}).id == "mimir-a"


# --- API: each request goes to its own connection --------------------------------------------


def _hosts_and_tenants(backend: FakeBackend) -> list[tuple[str, str | None]]:
    return [(r["host"], r["headers"].get("x-scope-orgid")) for r in backend.requests]


@pytest.mark.parametrize("connection_id, host, tenant", [("mimir-a", "mimir-a.test", "team-a"), ("mimir-b", "mimir-b.test", "team-b")])
def test_label_values_uses_the_named_connection(api: TestClient, backend: FakeBackend, connection_id, host, tenant) -> None:
    res = api.get("/api/prometheus/label-values", params={"label": "service", "connection_id": connection_id})

    assert res.status_code == 200
    assert _hosts_and_tenants(backend) == [(host, tenant)]
    assert backend.requests[0]["path"] == "/prometheus/api/v1/label/service/values"


def test_preview_uses_the_named_connection_and_its_auth(api: TestClient, backend: FakeBackend) -> None:
    res = api.post(
        "/api/prometheus/preview",
        json={"connection_id": "mimir-b", "query": "up", "start": "2026-10-01T00:00:00Z", "end": "2026-10-01T01:00:00Z", "step": "60s"},
    )

    assert res.status_code == 200
    assert _hosts_and_tenants(backend) == [("mimir-b.test", "team-b")]
    assert backend.requests[0]["headers"]["authorization"] == "Bearer b-secret"


def test_test_connection_uses_the_named_connection(api: TestClient, backend: FakeBackend) -> None:
    res = api.post("/api/prometheus/test-connection", json={"connection_id": "mimir-b"})

    assert res.status_code == 200
    assert res.json()["available"] is True
    assert _hosts_and_tenants(backend) == [("mimir-b.test", "team-b")]


def test_direct_analysis_uses_the_named_connection(api: TestClient, backend: FakeBackend) -> None:
    res = api.post(
        "/api/analysis/prometheus",
        json={"connection_id": "mimir-b", "service": "checkout", "metric": "up", "query": "up", "start": "2026-10-01T00:00:00Z", "end": "2026-10-01T01:00:00Z", "step": "60s"},
    )

    # The fake backend returns no samples; what matters is which tenant was asked.
    assert res.status_code == 400
    assert _hosts_and_tenants(backend) == [("mimir-b.test", "team-b")]


def test_legacy_default_id_reaches_the_default_connection(api: TestClient, backend: FakeBackend) -> None:
    res = api.get("/api/prometheus/label-values", params={"label": "service"})

    assert res.status_code == 200
    assert _hosts_and_tenants(backend) == [("mimir-a.test", "team-a")]


def test_scope_options_use_the_named_connection_and_its_cluster_label(api: TestClient, backend: FakeBackend) -> None:
    res = api.get("/api/autonomous/scope-options", params={"connection_id": "mimir-b"})

    assert res.status_code == 200
    assert res.json()["cluster_label"] == "k8s_cluster"
    assert {host for host, _ in _hosts_and_tenants(backend)} == {"mimir-b.test"}


@pytest.mark.parametrize(
    "method, url, body",
    [
        ("get", "/api/prometheus/label-values?label=service&connection_id=nope", None),
        ("post", "/api/prometheus/test-connection", {"connection_id": "nope"}),
        ("post", "/api/prometheus/preview", {"connection_id": "nope", "query": "up", "start": "2026-10-01T00:00:00Z", "end": "2026-10-01T01:00:00Z", "step": "60s"}),
        ("post", "/api/analysis/prometheus", {"connection_id": "nope", "service": "checkout", "metric": "up", "query": "up", "start": "2026-10-01T00:00:00Z", "end": "2026-10-01T01:00:00Z", "step": "60s"}),
        ("get", "/api/autonomous/scope-options?connection_id=nope", None),
        ("post", "/api/autonomous/preview", {"connection_id": "nope", "monitoring_selection": {"categories": ["performance"]}}),
    ],
)
def test_unknown_connection_is_404_and_queries_nothing(api: TestClient, backend: FakeBackend, method, url, body) -> None:
    res = api.request(method.upper(), url, json=body)

    assert res.status_code == 404
    assert "nope" in res.json()["detail"]
    assert backend.requests == []


def test_connections_endpoint_lists_all_without_secrets(api: TestClient) -> None:
    payload = api.get("/api/prometheus/connections").json()

    assert [(c["id"], c["is_default"], c["configured"]) for c in payload["connections"]] == [
        ("mimir-a", True, True),
        ("mimir-b", False, True),
    ]
    assert payload["connections"][1]["match_labels"] == {"tenant": "team-b"}
    assert "b-secret" not in json.dumps(payload)
    assert "team-b" in json.dumps(payload)  # match labels are not secrets


# --- autonomous policies ---------------------------------------------------------------------

POLICY_BODY = {
    "name": "Team B coverage",
    "scope": {"all_services": True, "all_namespaces": True},
    "monitoring_selection": {"categories": ["performance"]},
    "execution": {"interval": "1m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
}


def test_policy_keeps_its_connection(api: TestClient) -> None:
    created = api.post("/api/autonomous/policies", json={**POLICY_BODY, "connection_id": "mimir-b"}).json()

    assert created["connection_id"] == "mimir-b"
    listed = api.get("/api/autonomous/policies").json()
    assert [p["connection_id"] for p in listed] == ["mimir-b"]
    updated = api.patch(f"/api/autonomous/policies/{created['id']}", json={**POLICY_BODY, "connection_id": "mimir-a"}).json()
    assert updated["connection_id"] == "mimir-a"


def test_policy_without_connection_uses_default_id(api: TestClient) -> None:
    created = api.post("/api/autonomous/policies", json=POLICY_BODY).json()

    assert created["connection_id"] == "default"


def test_policy_for_unknown_connection_is_rejected(api: TestClient) -> None:
    res = api.post("/api/autonomous/policies", json={**POLICY_BODY, "connection_id": "nope"})

    assert res.status_code == 404


def _make_due(policy_id: str) -> None:
    with get_session_local()() as db:
        policy = AutonomousPolicyRepository(db).get(policy_id)
        policy.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()


def test_scheduled_policy_queries_only_its_connection(api: TestClient) -> None:
    created = api.post("/api/autonomous/policies", json={**POLICY_BODY, "connection_id": "mimir-b", "schedule_minutes": 10}).json()
    _make_due(created["id"])

    fake_result = SimpleNamespace(status="completed")
    with (
        patch("backend.app.api.autonomous.preview_autonomous_plan", return_value=object()) as mock_preview,
        patch("backend.app.autonomous.scheduler.execute_autonomous_plan_once", return_value=fake_result) as mock_execute,
    ):
        _run_due_policies_once()

    assert mock_preview.call_args.args[1].config.id == "mimir-b"
    assert mock_execute.call_args.kwargs["prometheus"].config.id == "mimir-b"
    assert mock_execute.call_args.kwargs["config"].id == "mimir-b"


def test_scheduled_policy_for_removed_connection_fails_without_fallback(api: TestClient, connections_file) -> None:
    created = api.post("/api/autonomous/policies", json={**POLICY_BODY, "connection_id": "mimir-b", "schedule_minutes": 10}).json()
    _make_due(created["id"])
    connections_file.write_text("connections:\n  - {id: mimir-a, base_url: 'http://mimir-a.test'}\n")

    with patch("backend.app.autonomous.scheduler.execute_autonomous_plan_once") as mock_execute:
        _run_due_policies_once()

    mock_execute.assert_not_called()
    with get_session_local()() as db:
        policy = AutonomousPolicyRepository(db).get(created["id"])
        assert policy.last_run_status == "failed"
        assert policy.consecutive_failures == 1


# --- alert routing ---------------------------------------------------------------------------


@pytest.fixture()
def routed(client: TestClient):
    """Alert enrichment with two connections, each with its own fake query service."""
    connections = PrometheusConnections(
        connections=[
            PrometheusConnectionConfig(id="mimir-a", base_url="http://mimir-a.test", match_labels={"tenant": "team-a"}),
            PrometheusConnectionConfig(id="mimir-b", base_url="http://mimir-b.test", match_labels={"tenant": "team-b"}),
        ],
        default_id="mimir-a",
    )
    queries = {"mimir-a": FakeQueryService(), "mimir-b": FakeQueryService()}
    config = AlertEnrichmentConfig(enabled=True, slack_webhook_url="http://slack.example/hook", ui_base_url="http://ops.local")
    pipeline = FakePipeline()
    posted: list[dict] = []
    service = AlertEnrichmentService(
        config,
        connections,
        session_factory=lambda: get_session_local()(),
        query_service_factory=lambda connection: queries[connection.id],
        pipeline_runner=pipeline,
        poster=posted.append,
        sleep=lambda _: None,
        clock=lambda: NOW,
    )
    client.app.dependency_overrides[get_alert_enrichment_config] = lambda: config
    client.app.dependency_overrides[get_alert_enrichment_service] = lambda: service
    yield SimpleNamespace(client=client, queries=queries, pipeline=pipeline, posted=posted)
    client.app.dependency_overrides.clear()


def _alert_with(**labels: str) -> dict:
    payload = _payload()
    payload["alerts"][0]["labels"].update(labels)
    return payload


def test_alert_is_analysed_on_the_connection_its_labels_match(routed) -> None:
    routed.client.post("/api/integrations/alertmanager", json=_alert_with(tenant="team-b"))

    assert len(routed.queries["mimir-b"].calls) >= 1
    assert routed.queries["mimir-a"].calls == []
    assert routed.pipeline.calls[0]["run_metadata"]["datasource_uid"] == "mimir-b"


def test_unmatched_alert_goes_to_the_default_connection(routed) -> None:
    routed.client.post("/api/integrations/alertmanager", json=_alert_with())

    assert routed.queries["mimir-b"].calls == []
    assert routed.pipeline.calls[0]["run_metadata"]["datasource_uid"] == "mimir-a"


def test_finding_from_another_connection_is_not_reused(routed) -> None:
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(
            id="auto-a", source_type="prometheus", service="checkout-api", metric_name=METRIC_KEY,
            start_time=STARTS_AT - timedelta(hours=1), end_time=STARTS_AT, sample_count=10, status="completed",
            connection_id="mimir-a",
        ))
        db.add(FindingEntity(
            analysis_run_id="auto-a", service="checkout-api", metric_name=METRIC_KEY,
            title="Autonomous: latency shift for team A", summary="found by the scheduler", category="baseline_shift",
            health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
            created_at=STARTS_AT - timedelta(minutes=5),
        ))
        db.commit()

    routed.client.post("/api/integrations/alertmanager", json=_alert_with(tenant="team-b"))

    assert len(routed.pipeline.calls) == 1
    with get_session_local()() as db:
        row = db.query(AlertEnrichmentEntity).one()
        assert row.analysis_status != "reused"


def test_finding_from_the_same_connection_is_reused(routed) -> None:
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(
            id="auto-b", source_type="prometheus", service="checkout-api", metric_name=METRIC_KEY,
            start_time=STARTS_AT - timedelta(hours=1), end_time=STARTS_AT, sample_count=10, status="completed",
            connection_id="mimir-b",
        ))
        db.add(FindingEntity(
            analysis_run_id="auto-b", service="checkout-api", metric_name=METRIC_KEY,
            title="Autonomous: latency shift for team B", summary="found by the scheduler", category="baseline_shift",
            health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
            created_at=STARTS_AT - timedelta(minutes=5),
        ))
        db.commit()

    routed.client.post("/api/integrations/alertmanager", json=_alert_with(tenant="team-b"))

    assert routed.pipeline.calls == []
    with get_session_local()() as db:
        assert db.query(AlertEnrichmentEntity).one().analysis_status == "reused"


# --- status ----------------------------------------------------------------------------------


def test_status_reports_each_connection(api: TestClient, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion_status, "_prometheus_checks", {})

    prometheus = api.get("/api/ingestion/status").json()["sources"]["prometheus"]

    assert prometheus["configured"] is True
    assert prometheus["reachable"] is True
    assert [(c["id"], c["reachable"]) for c in prometheus["connections"]] == [("mimir-a", True), ("mimir-b", True)]
    assert {host for host, _ in _hosts_and_tenants(backend)} == {"mimir-a.test", "mimir-b.test"}


def test_connections_endpoint_hides_credentials_in_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "https://reader:hunter2@prom.example.com:9090/prometheus")

    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        payload = client.get("/api/prometheus/connections").json()

    assert payload["connections"][0]["base_url"] == "https://prom.example.com:9090/prometheus"


# --- runs remember their connection ----------------------------------------------------------


@pytest.mark.parametrize("metadata, expected", [({"connection_id": "mimir-b"}, "mimir-b"), ({"datasource_uid": "grafana-uid"}, None), (None, None)])
def test_analysis_run_stores_only_an_explicit_connection_id(metadata, expected) -> None:
    import pandas as pd

    from intelligence.pipeline import SignalPipeline

    stored: list[dict] = []
    pipeline = SimpleNamespace(
        config=SimpleNamespace(input=SimpleNamespace(source_type="prometheus", provider="prometheus")),
        store=SimpleNamespace(create_analysis_run=stored.append),
    )
    normalized = pd.DataFrame({"timestamp": [NOW], "metric_name": ["up"], "service": ["checkout"], "value": [1.0]})

    SignalPipeline._create_analysis_run(pipeline, "run-x", normalized, run_metadata=metadata)

    assert stored[0]["connection_id"] == expected


def test_findings_say_which_connection_their_run_queried(api: TestClient) -> None:
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(
            id="run-b", source_type="prometheus", service="checkout-api", metric_name=METRIC_KEY,
            start_time=STARTS_AT - timedelta(hours=1), end_time=STARTS_AT, sample_count=10, status="completed",
            connection_id="mimir-b",
        ))
        for run_id in ("run-b", "run-csv"):
            db.add(FindingEntity(
                analysis_run_id=run_id, service="checkout-api", metric_name=METRIC_KEY,
                title=f"shift in {run_id}", summary="s", category="baseline_shift",
                health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
            ))
        db.commit()

    findings = {f["analysis_run_id"]: f["connection_id"] for f in api.get("/api/findings").json()}

    assert findings == {"run-b": "mimir-b", "run-csv": None}


def test_label_values_can_be_narrowed_to_matching_series_and_a_time_range(api: TestClient, backend: FakeBackend) -> None:
    res = api.get(
        "/api/prometheus/label-values",
        params=[("label", "cluster"), ("connection_id", "mimir-b"), ("match", 'up{service="checkout"}'),
                ("start", "2026-10-01T00:00:00Z"), ("end", "2026-10-02T00:00:00Z")],
    )

    assert res.status_code == 200
    params = backend.requests[0]["params"]
    assert params["match[]"] == 'up{service="checkout"}'
    assert "start" in params and "end" in params


def test_connections_endpoint_reports_each_cluster_label(api: TestClient) -> None:
    payload = api.get("/api/prometheus/connections").json()

    assert [c["cluster_label"] for c in payload["connections"]] == ["cluster", "k8s_cluster"]
