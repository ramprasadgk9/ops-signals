"""GET /api/ingestion/status - the Overview page's "is any data getting in?" read.

The regression that matters most: an install that already has data must never report
has_any_data=False, or the Overview would swap its KPIs for the first-run panel."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, AnalysisRunEntity, OtlpPendingPointEntity
from backend.app.otlp import metrics as otlp_metrics

STATUS = "/api/ingestion/status"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The OTLP "last received" time is process-wide, and other test files post OTLP points.
    monkeypatch.setattr(otlp_metrics, "_last_received_at", None)
    for name in (
        "OPS_SIGNALS_PROMETHEUS_URL",
        "OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED",
        "OPS_SIGNALS_ALERT_RECEIVER_TOKEN",
        "OPS_SIGNALS_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as test_client:
        yield test_client


def _otlp_request() -> ExportMetricsServiceRequest:
    request = ExportMetricsServiceRequest()
    rm = request.resource_metrics.add()
    rm.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value="payments-api")))
    metric = rm.scope_metrics.add().metrics.add()
    metric.name = "cpu_usage"
    point = metric.gauge.data_points.add()
    point.time_unix_nano = int(time.time() * 1e9)
    point.as_double = 42.0
    return request


def _alert(created_at: datetime) -> AlertEnrichmentEntity:
    return AlertEnrichmentEntity(
        fingerprint=f"fp-{created_at.isoformat()}",
        source="alertmanager",
        alert_name="HighLatency",
        status="firing",
        starts_at=created_at,
        created_at=created_at,
    )


def test_fresh_install_reports_no_data_and_every_source_idle(client: TestClient) -> None:
    body = client.get(STATUS).json()

    assert body["has_any_data"] is False
    assert body["sources"]["otlp"] == {"endpoint_path": "/api/otlp/v1/metrics", "last_received_at": None}
    assert body["sources"]["alertmanager"] == {
        "endpoint_path": "/api/integrations/alertmanager",
        "enabled": False,
        "token_required": False,
        "last_received_at": None,
        "received_24h": 0,
    }
    assert body["sources"]["prometheus"] == {"configured": False}


def test_otlp_push_marks_otlp_as_receiving(client: TestClient) -> None:
    response = client.post(
        "/api/otlp/v1/metrics",
        content=_otlp_request().SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert response.status_code == 200

    body = client.get(STATUS).json()
    assert body["has_any_data"] is True
    assert body["sources"]["otlp"]["last_received_at"] is not None


def test_otlp_backlog_survives_a_restart_without_the_in_memory_timestamp(client: TestClient) -> None:
    received_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    with get_session_local()() as db:
        db.add(
            OtlpPendingPointEntity(
                metric_name="cpu_usage",
                metric_type="gauge",
                timestamp=received_at,
                value=1.0,
                service="payments-api",
                received_at=received_at,
            )
        )
        db.commit()

    body = client.get(STATUS).json()
    assert body["has_any_data"] is True
    assert datetime.fromisoformat(body["sources"]["otlp"]["last_received_at"]) == received_at


def test_alerts_report_latest_and_only_count_the_last_24h(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add_all([_alert(now - timedelta(minutes=3)), _alert(now - timedelta(days=2))])
        db.commit()

    alertmanager = client.get(STATUS).json()["sources"]["alertmanager"]
    assert alertmanager["received_24h"] == 1
    assert datetime.fromisoformat(alertmanager["last_received_at"]) == now - timedelta(minutes=3)


def test_existing_analysis_history_is_never_treated_as_a_fresh_install(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add(
            AnalysisRunEntity(
                id="run-csv-1",
                source_type="csv",
                service="checkout",
                metric_name="latency",
                start_time=now - timedelta(hours=1),
                end_time=now,
                sample_count=60,
                status="completed",
            )
        )
        db.commit()

    body = client.get(STATUS).json()
    assert body["has_any_data"] is True
    # A CSV run is history, not OTLP traffic.
    assert body["sources"]["otlp"]["last_received_at"] is None


def test_configured_sources_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_RECEIVER_TOKEN", "receiver-secret")
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        sources = client.get(STATUS).json()["sources"]

    assert sources["prometheus"]["configured"] is True
    assert sources["alertmanager"]["enabled"] is True
    assert sources["alertmanager"]["token_required"] is True


def test_status_is_behind_the_api_token_and_never_leaks_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "api-secret")
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        assert client.get(STATUS).status_code == 401
        response = client.get(STATUS, headers={"Authorization": "Bearer api-secret"})

    assert response.status_code == 200
    assert "api-secret" not in response.text
    # The receiver falls back to the API token, so the UI should say a token is needed.
    assert response.json()["sources"]["alertmanager"]["token_required"] is True


def test_a_failed_run_alone_does_not_end_the_first_run_state(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add(
            AnalysisRunEntity(
                id="run-failed-1",
                source_type="csv",
                service="checkout",
                metric_name="latency",
                start_time=now - timedelta(hours=1),
                end_time=now,
                sample_count=0,
                status="failed",
            )
        )
        db.commit()

    assert client.get(STATUS).json()["has_any_data"] is False
