from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.direct_prometheus import get_prometheus_query_service
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from backend.app.services.prometheus_service import parse_step_seconds, validate_range


class FakePrometheusService:
    def __init__(self, preview: PrometheusPreviewOut):
        self._preview = preview

    def test_connection(self):
        return True, "2.52.0", 7, "Connection successful"

    def label_values(self, label: str):
        if label == "service":
            return ["drift-lab", "ruptures-lab", "trend-lab"]
        if label == "__name__":
            return ["cpu_usage", "ops_signal_lab_value", "request_latency_p95"]
        return []

    def preview(self, query: str, start: datetime, end: datetime, step: str):
        return self._preview


def _preview(series_count: int = 1, sample_count: int = 2) -> PrometheusPreviewOut:
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    samples = [
        PrometheusSeriesSample(timestamp=start, value=1.0),
        PrometheusSeriesSample(timestamp=start + timedelta(minutes=5), value=2.0),
    ][:sample_count]
    series = [
        PrometheusSeriesOut(labels={"__name__": "cpu_usage", "service": f"checkout-{index}"}, samples=samples)
        for index in range(series_count)
    ]
    return PrometheusPreviewOut(
        query="cpu_usage{service=\"checkout\"}",
        start=start,
        end=start + timedelta(minutes=10),
        step="5m",
        step_seconds=300,
        series_count=series_count,
        sample_count=sum(len(item.samples) for item in series),
        series=series,
        warnings=[],
    )


def test_prometheus_connections_do_not_expose_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN", "secret-token")
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        res = client.get("/api/prometheus/connections")

    assert res.status_code == 200
    payload = res.json()
    assert payload["connections"][0]["configured"] is True
    assert "secret-token" not in str(payload)


def test_prometheus_preview_uses_configured_service() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview())

    with TestClient(app) as client:
        res = client.post(
            "/api/prometheus/preview",
            json={
                "connection_id": "default",
                "query": "cpu_usage{service=\"checkout\"}",
                "start": "2026-07-26T10:00:00Z",
                "end": "2026-07-26T11:00:00Z",
                "step": "5m",
            },
        )

    assert res.status_code == 200
    assert res.json()["series_count"] == 1
    assert res.json()["sample_count"] == 2


def test_prometheus_label_values_returns_real_labels() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview())

    with TestClient(app) as client:
        res = client.get("/api/prometheus/label-values", params={"label": "service"})

    assert res.status_code == 200
    assert res.json() == {
        "connection_id": "default",
        "label": "service",
        "values": ["drift-lab", "ruptures-lab", "trend-lab"],
    }


def test_direct_prometheus_analysis_rejects_empty_result() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview(sample_count=0))

    with TestClient(app) as client:
        res = client.post(
            "/api/analysis/prometheus",
            json={
                "connection_id": "default",
                "query": "cpu_usage{service=\"checkout\"}",
                "service": "checkout",
                "metric": "cpu_usage",
                "start": "2026-07-26T10:00:00Z",
                "end": "2026-07-26T11:00:00Z",
                "step": "5m",
                "analyzer": "ruptures",
                "execution_mode": "persist",
            },
        )

    assert res.status_code == 400
    assert "no samples" in res.json()["detail"]


def test_direct_prometheus_analysis_requires_single_series() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview(series_count=2))

    with TestClient(app) as client:
        res = client.post(
            "/api/analysis/prometheus",
            json={
                "connection_id": "default",
                "query": "cpu_usage",
                "service": "checkout",
                "metric": "cpu_usage",
                "start": "2026-07-26T10:00:00Z",
                "end": "2026-07-26T11:00:00Z",
                "step": "5m",
                "analyzer": "ruptures",
                "execution_mode": "persist",
            },
        )

    assert res.status_code == 400
    assert "returned 2 series" in res.json()["detail"]


def test_prometheus_step_and_window_validation() -> None:
    config = PrometheusConnectionConfig(min_step_seconds=10, max_window_days=1)

    assert parse_step_seconds("5m", config) == 300
    with pytest.raises(HTTPException):
        parse_step_seconds("1s", config)
    with pytest.raises(HTTPException):
        validate_range(
            datetime(2026, 7, 24, tzinfo=timezone.utc),
            datetime(2026, 7, 26, tzinfo=timezone.utc),
            300,
            config,
        )
