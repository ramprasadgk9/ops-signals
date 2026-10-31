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
    # Step 1 of docs/access.md: lock the API, with the command to copy.
    assert (checks["login"]["docs"], checks["login"]["step"], checks["login"]["action"]) == ("docs/access.md", 1, "lock_api")
    assert "OPS_SIGNALS_API_TOKEN" in checks["login"]["snippet"]
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
    # A token alone: nobody signs in to the web UI, so it has no roles.
    assert (checks["login"]["status"], checks["login"]["step"], checks["login"]["action"]) == ("warn", 2, "choose_sign_in")
    assert checks["login"]["detail"].startswith("API locked. But nobody signs in to the web UI")
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


PAYMENTS_OVERRIDE = """
overrides:
  payments_memory:
    scope: {service: payments-api}
    reason: Memory grows slowly here.
    analyzers:
      trend: {finding_rules: {min_slope_percent: 5}}
"""


def _seed_run(service: str, metric: str = "memory") -> None:
    now = datetime.utcnow()
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(id=f"run-{service}", source_type="prometheus", service=service, metric_name=metric,
                                 start_time=now - timedelta(hours=1), end_time=now, sample_count=10, status="completed"))
        db.commit()


def test_per_service_settings_are_off_until_a_file_is_added(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_check, "OVERRIDES_DIR", tmp_path)
    with _client() as client:
        check = _by_id(client.get(CHECK).json())["analyzer_overrides"]

    assert (check["group"], check["status"], check["action"]) == ("optional", "off", "how_to_set")
    assert check["detail"] == "Not used: every service runs on the default analyzer settings."
    # How to set: the file to copy, and each setting a team can change with its range.
    assert check["fix"][0].startswith("Copy config/analyzer_overrides.d/payments-team.yml.example")
    assert any(step.startswith("Trend Analysis: Smallest steady climb") and "from 1 to 100" in step for step in check["fix"])


def test_per_service_settings_in_use_are_listed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "payments-team.yml").write_text(PAYMENTS_OVERRIDE)
    monkeypatch.setattr(setup_check, "OVERRIDES_DIR", tmp_path)
    with _client() as client:
        _seed_run("payments-api")
        check = _by_id(client.get(CHECK).json())["analyzer_overrides"]

    assert check["status"] == "ok"
    assert check["detail"] == "1 override in 1 file in use: payments-team.yml"


def test_a_skipped_file_and_an_override_that_matches_nothing_are_flagged(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "payments-team.yml").write_text(PAYMENTS_OVERRIDE.replace("payments-api", "payment-api"))
    (tmp_path / "checkout-team.yml").write_text(PAYMENTS_OVERRIDE.replace("payments_memory", "checkout_trend").replace("min_slope_percent: 5", "min_slope_percent: 500"))
    monkeypatch.setattr(setup_check, "OVERRIDES_DIR", tmp_path)
    with _client() as client:
        _seed_run("payments-api")
        check = _by_id(client.get(CHECK).json())["analyzer_overrides"]

    assert check["status"] == "warn"
    assert check["detail"] == "1 override in 1 file in use · 1 file skipped · 1 override matched nothing in the last 7 days"
    assert check["fix"][0].startswith("checkout-team.yml skipped: override 'checkout_trend': 'trend.finding_rules.min_slope_percent' must be between 1 and 100, got 500")
    assert check["fix"][0].endswith("Its services run on the default settings.")
    # A near-miss service name gets a hint: a typo is the usual reason.
    assert check["fix"][1] == "payments_memory (payments-team.yml) matched no series in the last 7 days. Check service: payment-api: seen services include payments-api."
