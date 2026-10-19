"""GET /api/setup/check - the Setup check page: what works, what to fix, and how.

What matters most: a broken part shows as a failed check with a fix that fits how it failed, the
request itself never fails, and no secret (token, password) ever appears in the answer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.api import setup_check
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity
from backend.app.otlp import metrics as otlp_metrics
from backend.app.services.prometheus_service import ConnectionProbe, PrometheusQueryService

CHECK = "/api/setup/check"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otlp_metrics, "_last_received_at", None)
    for name in (
        "OPS_SIGNALS_PROMETHEUS_URL",
        "OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN",
        "OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE",
        "OPS_SIGNALS_API_TOKEN",
        "OPS_SIGNALS_ENABLE_TESTING_API",
        "OPS_SIGNALS_ALLOW_FILE_WRITES",
        "OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED",
        "OPS_SIGNALS_SLACK_ENABLED",
        "OPS_SIGNALS_SLACK_WEBHOOK_URL",
        "OPS_SIGNALS_TICKETING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def _client() -> TestClient:
    return TestClient(create_app("sqlite+pysqlite:///:memory:"))


def _by_id(body: dict) -> dict[str, dict]:
    return {check["id"]: check for check in body["checks"]}


def test_fresh_install_says_what_is_missing_and_never_fails() -> None:
    with _client() as client:
        res = client.get(CHECK)

    assert res.status_code == 200
    checks = _by_id(res.json())
    assert checks["backend"]["status"] == "ok"
    assert checks["database"]["status"] == "ok"
    assert (checks["metrics"]["group"], checks["metrics"]["status"]) == ("required", "fail")
    assert "OPS_SIGNALS_PROMETHEUS_URL" in checks["metrics"]["snippet"]
    assert (checks["login"]["group"], checks["login"]["status"]) == ("recommended", "warn")
    assert checks["login"]["docs"] == "docs/security-model.md"
    assert (checks["first_analysis"]["status"], checks["first_analysis"]["action"]) == ("warn", "run_analysis")
    assert checks["risky_switches"]["status"] == "ok"
    for optional in ("alerts", "events", "notifications", "ticketing", "ai", "schedule"):
        assert (checks[optional]["group"], checks[optional]["status"]) == ("optional", "off"), optional


def test_a_reachable_prometheus_is_green_and_otlp_becomes_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setattr(PrometheusQueryService, "probe", lambda self: ConnectionProbe(True, "2.53.0", 42, "Connection successful", "/api/v1/status/buildinfo"))
    with _client() as client:
        checks = _by_id(client.get(CHECK).json())

    connection = checks["connection:default"]
    assert (connection["group"], connection["status"], connection["action"]) == ("required", "ok", "test_connection")
    assert connection["detail"] == "Answered in 42 ms · version 2.53.0"
    assert "metrics" not in checks
    assert (checks["otlp"]["group"], checks["otlp"]["status"]) == ("optional", "off")


def test_api_token_and_risky_switches_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "s3cret-token")
    monkeypatch.setenv("OPS_SIGNALS_ENABLE_TESTING_API", "true")
    monkeypatch.setenv("OPS_SIGNALS_ALLOW_FILE_WRITES", "true")
    with _client() as client:
        assert client.get(CHECK).status_code == 401
        res = client.get(CHECK, headers={"Authorization": "Bearer s3cret-token"})

    checks = _by_id(res.json())
    assert checks["login"]["status"] == "ok"
    assert checks["risky_switches"]["status"] == "warn"
    assert checks["risky_switches"]["detail"].startswith("2 switches are on")
    assert "s3cret-token" not in res.text


def test_a_past_analysis_run_completes_first_analysis() -> None:
    now = datetime.utcnow()
    with _client() as client:
        with get_session_local()() as db:
            db.add(AnalysisRunEntity(id="run-1", source_type="prometheus", service="checkout", metric_name="cpu",
                                     start_time=now - timedelta(hours=1), end_time=now, sample_count=10, status="completed"))
            db.commit()
        checks = _by_id(client.get(CHECK).json())

    assert checks["first_analysis"]["status"] == "ok"
    assert checks["first_analysis"]["detail"].startswith("1 analysis run ·")


def _connection(**overrides) -> PrometheusConnectionConfig:
    return PrometheusConnectionConfig(**({"id": "mimir-eu", "name": "mimir-eu", "base_url": "https://mimir-eu.internal/prometheus"} | overrides))


def test_a_rejected_login_asks_for_a_token_with_config_to_copy() -> None:
    probe = ConnectionProbe(False, None, 85, "unauthorized", "/api/v1/status/buildinfo", 401)
    check = setup_check.connection_check(_connection(), probe, single=False)

    assert check.status == "fail"
    assert check.detail.startswith("Login rejected (401)")
    assert check.tried == "GET https://mimir-eu.internal/prometheus/api/v1/status/buildinfo\n-> 401 unauthorized  (after 85 ms)"
    assert "bearer_token: ${MIMIR_EU_TOKEN}" in check.snippet

    single = setup_check.connection_check(_connection(id="default"), probe, single=True)
    assert single.snippet is None
    assert any("OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN" in step for step in single.fix)


def test_unreachable_localhost_explains_containers() -> None:
    probe = ConnectionProbe(False, None, 3, "Prometheus connection failed", "/api/v1/status/buildinfo", 503)
    local = setup_check.connection_check(_connection(base_url="http://localhost:9090"), probe, single=True)
    remote = setup_check.connection_check(_connection(base_url="http://prom.internal:9090"), probe, single=True)

    assert local.detail == "Can't reach localhost."
    assert "container" in local.cause
    assert "host.docker.internal" in local.fix[0]
    assert "container" not in remote.cause


def test_not_found_and_timeout_get_their_own_fix() -> None:
    not_found = setup_check.connection_check(_connection(), ConnectionProbe(False, None, 5, "not found", "/api/v1/query?query=vector(1)", 404), single=True)
    timeout = setup_check.connection_check(_connection(), ConnectionProbe(False, None, 5000, "Prometheus request timed out", "/api/v1/status/buildinfo", 504), single=True)

    assert "/prometheus" in not_found.cause
    assert timeout.detail == "No answer within 5 seconds."


def test_a_password_in_the_url_never_appears_in_the_answer() -> None:
    probe = ConnectionProbe(False, None, 5, "unauthorized", "/api/v1/status/buildinfo", 401)
    check = setup_check.connection_check(_connection(base_url="https://alice:hunter2@mimir-eu.internal/prometheus", bearer_token="tok-123"), probe, single=False)

    text = json.dumps(check.model_dump())
    assert "hunter2" not in text and "alice" not in text and "tok-123" not in text


def test_otlp_that_went_quiet_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timezone

    monkeypatch.setattr(otlp_metrics, "_last_received_at", datetime.now(timezone.utc) - timedelta(days=7))
    with _client() as client:
        checks = _by_id(client.get(CHECK).json())

    # With no Prometheus, OpenTelemetry is the only source, so a stopped one is a needed fix.
    assert (checks["otlp"]["group"], checks["otlp"]["status"]) == ("required", "fail")
    assert checks["otlp"]["detail"] == "Stopped: the last batch came 7d ago."
