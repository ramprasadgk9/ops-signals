"""GET /api/alerts - the read side of the alert receivers, behind the Integrations page's
"Recent alerts" list and the linked-alert badges on findings and cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.api.alerts import get_alert_enrichment_service
from backend.app.config import AlertEnrichmentConfig, PrometheusConnectionConfig, get_alert_enrichment_config
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, FindingEntity, OperationalCaseEntity

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(autouse=True)
def no_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN", raising=False)
    monkeypatch.delenv("OPS_SIGNALS_ALERT_RECEIVER_TOKEN", raising=False)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as test_client:
        yield test_client


def _alert(name: str, *, minutes_ago: int, status: str = "firing", service: str = "checkout-api", finding_id: int | None = None, **extra) -> AlertEnrichmentEntity:
    created_at = NOW - timedelta(minutes=minutes_ago)
    return AlertEnrichmentEntity(
        fingerprint=f"fp-{name}-{minutes_ago}",
        source="alertmanager",
        alert_name=name,
        status=status,
        service=service,
        severity="critical",
        starts_at=created_at,
        created_at=created_at,
        labels_json={"service": service, "alertname": name},
        annotations_json=extra.pop("annotations", {}),
        finding_id=finding_id,
        message_json={"blocks": ["slack message stays out of the list"]},
        **extra,
    )


def _seed_finding_with_case() -> tuple[int, int]:
    with get_session_local()() as db:
        finding = FindingEntity(metric_name="latency", service="checkout-api", title="Latency shift", summary="p95 up", category="behavior_change", health_status="critical")
        db.add(finding)
        db.flush()
        case = OperationalCaseEntity(finding_id=finding.id, analysis_run_id="run-1", case_title="Latency shift", finding_snapshot={})
        db.add(case)
        db.commit()
        return finding.id, case.id


def test_empty_list_when_no_alerts_received(client: TestClient) -> None:
    response = client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == []


def test_lists_newest_first_with_summary_and_linked_case(client: TestClient) -> None:
    finding_id, case_id = _seed_finding_with_case()
    with get_session_local()() as db:
        db.add_all(
            [
                _alert("DiskFull", minutes_ago=60, status="resolved", ends_at=NOW - timedelta(minutes=30)),
                _alert("HighLatency", minutes_ago=3, finding_id=finding_id, annotations={"summary": "p95 above 300ms"}, analysis_status="completed"),
            ]
        )
        db.commit()

    body = client.get("/api/alerts").json()

    assert [item["alert_name"] for item in body] == ["HighLatency", "DiskFull"]
    latest = body[0]
    assert latest["summary"] == "p95 above 300ms"
    assert latest["finding_id"] == finding_id
    assert latest["case_id"] == case_id
    assert latest["analysis_status"] == "completed"
    assert datetime.fromisoformat(latest["received_at"]) == NOW - timedelta(minutes=3)
    assert "message_json" not in latest and "enrichment_json" not in latest
    # No annotation summary: fall back to the alert name, and no case when nothing is linked.
    assert body[1]["summary"] == "DiskFull"
    assert body[1]["case_id"] is None
    assert body[1]["ends_at"] is not None


def test_filters_by_status_service_finding_and_since(client: TestClient) -> None:
    finding_id, _ = _seed_finding_with_case()
    with get_session_local()() as db:
        db.add_all(
            [
                _alert("A", minutes_ago=5, finding_id=finding_id),
                _alert("B", minutes_ago=10, status="resolved"),
                _alert("C", minutes_ago=3 * 24 * 60, service="payments-api"),
            ]
        )
        db.commit()

    names = lambda params: [item["alert_name"] for item in client.get("/api/alerts", params=params).json()]  # noqa: E731
    assert names({"status": "firing"}) == ["A", "C"]
    assert names({"service": "payments-api"}) == ["C"]
    assert names({"finding_id": finding_id}) == ["A"]
    assert names({"since": (NOW - timedelta(hours=24)).isoformat()}) == ["A", "B"]
    assert names({"limit": 1}) == ["A"]


def test_rejects_out_of_range_limit_and_unknown_status(client: TestClient) -> None:
    assert client.get("/api/alerts", params={"limit": 0}).status_code == 422
    assert client.get("/api/alerts", params={"limit": 501}).status_code == 422
    assert client.get("/api/alerts", params={"status": "pending"}).status_code == 422


def test_listing_needs_the_api_token_even_though_posting_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "api-secret")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_RECEIVER_TOKEN", "receiver-secret")
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        assert client.get("/api/alerts").status_code == 401
        # The receiver token is for posting alerts, not for reading them back.
        assert client.get("/api/alerts", headers={"Authorization": "Bearer receiver-secret"}).status_code == 401
        assert client.get("/api/alerts", headers={"Authorization": "Bearer api-secret"}).status_code == 200


def _test_alert_client(client: TestClient, **config_overrides):
    """Real enrichment service, no Prometheus configured, Slack captured instead of posted."""
    config = AlertEnrichmentConfig(**{"enabled": True, "slack_webhook_url": "http://slack.example/hook", **config_overrides})
    posted: list[dict] = []
    service = AlertEnrichmentService(
        config,
        PrometheusConnectionConfig(),
        session_factory=lambda: get_session_local()(),
        poster=posted.append,
        sleep=lambda _: None,
    )
    client.app.dependency_overrides[get_alert_enrichment_config] = lambda: config
    client.app.dependency_overrides[get_alert_enrichment_service] = lambda: service
    return posted


def test_test_alert_runs_the_real_receive_and_notify_path(client: TestClient) -> None:
    posted = _test_alert_client(client)

    first = client.post("/api/integrations/alertmanager/test")
    second = client.post("/api/integrations/alertmanager/test")

    assert first.status_code == 202 and second.status_code == 202
    # A fresh fingerprint per click: the second test is a new alert, not a duplicate.
    assert first.json()["accepted"] == 1 and second.json()["accepted"] == 1
    body = client.get("/api/alerts").json()
    assert [item["alert_name"] for item in body] == ["OpsSignalsTestAlert", "OpsSignalsTestAlert"]
    assert body[0]["source"] == "test"
    assert body[0]["summary"] == "Test alert sent from the Ops Signals Integrations page"
    assert body[0]["labels"]["ops_signals_test"] == "true"
    # It went all the way through, including the Slack post.
    assert len(posted) == 2
    client.app.dependency_overrides.clear()


def test_test_alert_reports_disabled_enrichment_without_storing_anything(client: TestClient) -> None:
    _test_alert_client(client, enabled=False)

    response = client.post("/api/integrations/alertmanager/test")

    assert response.status_code == 202
    assert response.json()["disabled"] is True
    assert client.get("/api/alerts").json() == []
    client.app.dependency_overrides.clear()


def test_test_alert_is_not_a_public_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "api-secret")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_RECEIVER_TOKEN", "receiver-secret")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED", "false")
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        assert client.post("/api/integrations/alertmanager/test").status_code == 401
        assert client.post("/api/integrations/alertmanager/test", headers={"Authorization": "Bearer receiver-secret"}).status_code == 401
        assert client.post("/api/integrations/alertmanager/test", headers={"Authorization": "Bearer api-secret"}).status_code == 202


def test_each_alert_carries_its_deploy_timing_matched_changes_and_pod_breakdown(client: TestClient) -> None:
    breakdown = {"status": "ok", "label": "pod", "spread": "partial", "parts_total": 6, "parts_changed": 2}
    enrichment = {
        "analysis": {
            "status": "analyzed",
            "timing": {"basis": "step_change", "time": "2026-10-01T21:32:00+00:00", "analyzer_id": "ruptures", "trend_direction": None},
            "finding": {"id": 7, "title": "Latency shift", "breakdown": breakdown},
        },
        "changes": {
            "service_has_any_events": True,
            "window_before_minutes": 30,
            "matches": [{"id": 3, "event_type": "deploy", "version": "v2.4.38", "author": "demo",
                         "url": "https://example.com/r", "timestamp": "2026-10-01T21:31:00+00:00", "minutes_before_anchor": 1.0},
                        {"id": 4, "event_type": "deploy", "version": "2.4.39", "timestamp": "2026-10-01T21:30:00+00:00",
                         "minutes_before_anchor": 2.0, "source": "ops-signals:build_info"}],
        },
    }
    with get_session_local()() as db:
        db.add_all([
            _alert("CheckoutLatencyHigh", minutes_ago=2, enrichment_json=enrichment),
            _alert("NotEnrichedYet", minutes_ago=5),
        ])
        db.commit()

    enriched, pending = client.get("/api/alerts").json()

    assert enriched["timing"]["basis"] == "step_change"
    assert [(change["version"], change["minutes_before_anchor"], change["source"]) for change in enriched["changes"]] == [
        ("v2.4.38", 1.0, None), ("2.4.39", 2.0, "ops-signals:build_info")]
    assert enriched["deploy_discovery"] is True
    assert (enriched["change_window_before_minutes"], enriched["service_has_change_events"]) == (30, True)
    assert enriched["breakdown"] == breakdown
    assert "message_json" not in enriched and "enrichment_json" not in enriched
    assert (pending["timing"], pending["changes"], pending["service_has_change_events"], pending["breakdown"]) == (None, [], None, None)
