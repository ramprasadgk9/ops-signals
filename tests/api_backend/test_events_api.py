from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config


def test_create_single_event_defaults_timestamp_and_lists_it(client: TestClient) -> None:
    response = client.post(
        "/api/events",
        json={"service": "checkout-api", "type": "deploy", "version": "v2.3.1", "url": "https://ci.example/run/1"},
    )
    assert response.status_code == 201
    [event] = response.json()
    assert event["service"] == "checkout-api"
    assert event["type"] == "deploy"
    assert event["timestamp"]

    listed = client.get("/api/events", params={"service": "checkout-api"}).json()
    assert [item["version"] for item in listed] == ["v2.3.1"]


def test_batch_create_and_filters(client: TestClient) -> None:
    base = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    response = client.post(
        "/api/events",
        json=[
            {"service": "a", "type": "deploy", "timestamp": base.isoformat()},
            {"service": "a", "type": "config", "timestamp": (base + timedelta(hours=1)).isoformat()},
            {"service": "b", "type": "deploy", "timestamp": base.isoformat()},
        ],
    )
    assert response.status_code == 201
    assert len(response.json()) == 3

    assert len(client.get("/api/events", params={"service": "a"}).json()) == 2
    assert len(client.get("/api/events", params={"type": "deploy"}).json()) == 2
    since = (base + timedelta(minutes=30)).isoformat()
    assert [e["type"] for e in client.get("/api/events", params={"since": since}).json()] == ["config"]


def test_validation(client: TestClient) -> None:
    assert client.post("/api/events", json={"service": "a", "type": "bogus"}).status_code == 422
    assert client.post("/api/events", json={"service": " ", "type": "deploy"}).status_code == 422
    assert client.post("/api/events", json={"service": "a", "type": "deploy", "url": "ftp://x"}).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    assert client.post("/api/events", json={"service": "a", "type": "deploy", "timestamp": future}).status_code == 400
    too_many = [{"service": "a", "type": "deploy"}] * 101
    assert client.post("/api/events", json=too_many).status_code == 400


def test_events_token_is_enforced_when_configured(client: TestClient) -> None:
    client.app.dependency_overrides[get_alert_enrichment_config] = lambda: AlertEnrichmentConfig(events_token="s3cret")
    try:
        assert client.post("/api/events", json={"service": "a", "type": "deploy"}).status_code == 401
        ok = client.post(
            "/api/events", json={"service": "a", "type": "deploy"}, headers={"Authorization": "Bearer s3cret"}
        )
        assert ok.status_code == 201
    finally:
        client.app.dependency_overrides.pop(get_alert_enrichment_config, None)
