from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.direct_prometheus import get_prometheus_query_service
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity
from backend.app.services import recording_rules as recording_rules_module
from backend.app.services.prometheus_service import PrometheusQueryService
from backend.app.services.recording_rules import parse_recording_rules, recording_rules

PAYMENT_RULES = {
    "status": "success",
    "data": {
        "groups": [
            {
                "name": "payment-rules",
                "file": "/etc/prometheus/rules.yml",
                "interval": 60,
                "rules": [
                    {
                        "type": "recording",
                        "name": "payment_failure_rate_percent",
                        "query": '100 * sum(rate(payment_transactions_total{status="failed"}[5m])) / sum(rate(payment_transactions_total[5m]))',
                        "health": "ok",
                    }
                ],
            }
        ]
    },
}


class FakeRulesService:
    def __init__(self, payload=None, error: HTTPException | None = None, connection_id: str = "local"):
        self.config = PrometheusConnectionConfig(id=connection_id, base_url="http://prometheus:9090")
        self.payload = payload
        self.error = error
        self.calls: list[str | None] = []

    def rules(self, rule_type=None):
        self.calls.append(rule_type)
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture(autouse=True)
def _empty_cache():
    recording_rules_module.clear_cache()
    yield
    recording_rules_module.clear_cache()


def test_parse_reads_name_query_group_and_source_metrics() -> None:
    [rule] = parse_recording_rules(PAYMENT_RULES)

    assert rule.name == "payment_failure_rate_percent"
    assert rule.query.startswith("100 * sum(rate(payment_transactions_total")
    assert rule.group == "payment-rules"
    assert rule.interval_seconds == 60
    assert rule.health == "ok"
    assert rule.source_metrics == ["payment_transactions_total"]


def test_parse_skips_alerting_rules_from_a_server_that_ignores_type() -> None:
    payload = {"data": {"groups": [{"name": "mixed", "rules": [
        {"type": "alerting", "name": "HighErrors", "query": "error_rate > 0.05", "health": "ok"},
        {"type": "recording", "name": "service:error_rate:percent", "query": "100 * avg by (service) (error_rate)", "health": "ok"},
    ]}]}}

    assert [rule.name for rule in parse_recording_rules(payload)] == ["service:error_rate:percent"]


def test_parse_keeps_not_run_yet_and_failed_rules_with_their_error() -> None:
    payload = {"data": {"groups": [{"name": "g", "rules": [
        {"type": "recording", "name": "new_rule", "query": "sum(up)", "health": "unknown"},
        {"type": "recording", "name": "broken_rule", "query": "a / on(x) b", "health": "err", "lastError": "many-to-many matching not allowed"},
        {"type": "recording", "name": "odd_health", "query": "sum(up)", "health": "weird"},
    ]}]}}

    rules = {rule.name: rule for rule in parse_recording_rules(payload)}

    assert rules["new_rule"].health == "unknown"
    assert rules["broken_rule"].health == "err"
    assert rules["broken_rule"].last_error == "many-to-many matching not allowed"
    assert rules["odd_health"].health == "unknown"


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {"groups": None}}, {"data": {"groups": [None, {"rules": [None, {"type": "recording"}]}]}}])
def test_parse_tolerates_malformed_responses(payload) -> None:
    assert parse_recording_rules(payload) == []


def test_rules_asks_prometheus_for_recording_rules_only(monkeypatch) -> None:
    service = PrometheusQueryService(PrometheusConnectionConfig(id="local", base_url="http://prometheus:9090"))
    calls = []
    monkeypatch.setattr(service, "_get_json", lambda path, params: calls.append((path, params)) or PAYMENT_RULES)

    service.rules("record")
    service.rules()

    assert calls == [("/api/v1/rules", {"type": "record"}), ("/api/v1/rules", {})]


def test_recording_rules_are_cached_per_connection() -> None:
    service = FakeRulesService(PAYMENT_RULES)

    first = recording_rules(service)
    second = recording_rules(service)

    assert [rule.name for rule in second.rules] == ["payment_failure_rate_percent"]
    assert first is second
    assert service.calls == ["record", "alert"]


def test_unreadable_rules_give_an_empty_list_and_are_not_cached() -> None:
    service = FakeRulesService(error=HTTPException(status_code=404, detail="ruler not enabled"))

    result = recording_rules(service)
    recording_rules(service)

    assert result.rules == []
    assert result.message == "Couldn't read recording rules: ruler not enabled"
    assert service.calls == ["record", "record"]


def test_unconfigured_connection_is_still_an_error() -> None:
    service = FakeRulesService(error=HTTPException(status_code=400, detail="Prometheus is not configured."))

    with pytest.raises(HTTPException):
        recording_rules(service)


def test_recording_rules_endpoint() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeRulesService(PAYMENT_RULES, connection_id="default")

    with TestClient(app) as client:
        res = client.get("/api/prometheus/recording-rules")

    assert res.status_code == 200
    body = res.json()
    assert body["connection_id"] == "default"
    assert body["message"] is None
    assert body["rules"] == [{
        "name": "payment_failure_rate_percent",
        "query": '100 * sum(rate(payment_transactions_total{status="failed"}[5m])) / sum(rate(payment_transactions_total[5m]))',
        "group": "payment-rules",
        "interval_seconds": 60.0,
        "health": "ok",
        "last_error": None,
        "source_metrics": ["payment_transactions_total"],
        "alerts": [],
    }]
    # The server's file path isn't passed on.
    assert "file" not in body["rules"][0]


def test_single_run_read_says_which_connection_and_query_it_used() -> None:
    now = datetime.now(timezone.utc)
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        with get_session_local()() as db:
            db.add(AnalysisRunEntity(
                id="run-rule", source_type="prometheus", provider="prometheus", service="spike-lab",
                metric_name="service:error_rate:percent", start_time=now - timedelta(hours=1), end_time=now,
                sample_count=60, status="completed", connection_id="local",
                promql='service:error_rate:percent{service="spike-lab"}',
            ))
            db.commit()
        res = client.get("/api/analysis-runs/run-rule")

    assert res.status_code == 200
    assert res.json()["connection_id"] == "local"
    assert res.json()["promql"] == 'service:error_rate:percent{service="spike-lab"}'


def test_unknown_connection_is_a_404_the_ui_ignores() -> None:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        res = client.get("/api/prometheus/recording-rules", params={"connection_id": "removed-tenant"})

    assert res.status_code == 404
