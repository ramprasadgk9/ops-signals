from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.direct_prometheus import _multi_series_detail, _observed_interval, _prometheus_series_to_normalized, get_prometheus_query_service
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from backend.app.services.prometheus_service import parse_step_seconds, validate_range


class FakePrometheusService:
    def __init__(self, preview: PrometheusPreviewOut):
        self._preview = preview

    def test_connection(self):
        return True, "2.52.0", 7, "Connection successful"

    def label_values(self, label: str, **kwargs):
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


def test_observed_interval_uses_returned_sample_spacing() -> None:
    start = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
    samples = [
        PrometheusSeriesSample(timestamp=start, value=1.0),
        PrometheusSeriesSample(timestamp=start + timedelta(minutes=10), value=2.0),
        PrometheusSeriesSample(timestamp=start + timedelta(minutes=20), value=3.0),
    ]

    assert _observed_interval(samples, fallback_seconds=300) == "10m"


def test_prometheus_series_to_normalized_does_not_insert_empty_buckets() -> None:
    start = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
    samples = [
        PrometheusSeriesSample(timestamp=start, value=1.0),
        PrometheusSeriesSample(timestamp=start + timedelta(minutes=10), value=2.0),
        PrometheusSeriesSample(timestamp=start + timedelta(minutes=30), value=3.0),
    ]

    normalized = _prometheus_series_to_normalized(
        samples=samples,
        labels={"__name__": "ops_signal_lab_value", "service": "ruptures-lab", "instance": "mock:9101"},
        service="fallback-service",
        metric="fallback_metric",
    )

    assert len(normalized) == 3
    assert normalized["value"].isna().sum() == 0
    assert normalized["metric_name"].unique().tolist() == ["ops_signal_lab_value"]
    assert normalized["service"].unique().tolist() == ["ruptures-lab"]


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
    assert "matched 2 series" in res.json()["detail"]


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


def _series(*label_sets: dict[str, str]) -> list[PrometheusSeriesOut]:
    sample = PrometheusSeriesSample(timestamp=datetime(2026, 10, 1, tzinfo=timezone.utc), value=1.0)
    return [PrometheusSeriesOut(labels=labels, samples=[sample]) for labels in label_sets]


def test_multi_series_error_names_the_clusters_and_the_query_to_pick_one() -> None:
    series = _series(
        {"__name__": "request_latency_p95", "service": "checkout", "cluster": "eu", "instance": "a"},
        {"__name__": "request_latency_p95", "service": "checkout", "cluster": "us", "instance": "b"},
    )

    detail = _multi_series_detail('request_latency_p95{service="checkout"}', series, "cluster")

    assert detail == 'This query matched 2 clusters (eu, us). Add cluster="eu" to pick one: request_latency_p95{service="checkout",cluster="eu"}'


def test_multi_series_error_for_other_labels_and_complex_promql() -> None:
    series = _series({"pod": "p1"}, {"pod": "p2"})

    assert _multi_series_detail("up", series, "cluster") == 'This query matched 2 series, which differ by pod (p1, p2). Add pod="p1" to pick one: up{pod="p1"}'
    assert _multi_series_detail("sum by (pod) (rate(x[5m]))", series, "cluster").endswith('Add pod="p1" to pick one, or aggregate pod away.')


def test_run_analysis_reports_why_several_series_came_back() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview(series_count=2))

    with TestClient(app) as client:
        res = client.post(
            "/api/analysis/prometheus",
            json={"query": "cpu_usage", "service": "checkout", "metric": "cpu_usage",
                  "start": "2026-07-26T10:00:00Z", "end": "2026-07-26T11:00:00Z", "step": "5m"},
        )

    assert res.status_code == 400
    assert res.json()["detail"] == 'This query matched 2 series, which differ by service (checkout-0, checkout-1). Add service="checkout-0" to pick one: cpu_usage{service="checkout-0"}'


class PerPodPrometheusService(FakePrometheusService):
    """Four search-svc pods for the plain selector; one combined line for anything aggregated."""

    def __init__(self):
        self.queries: list[str] = []

    def preview(self, query: str, start: datetime, end: datetime, step: str):
        self.queries.append(query)
        begin = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
        pods = ["search-svc-0", "search-svc-1", "search-svc-2", "search-svc-3"]

        def value(pod: str, i: int) -> float:
            return 1150.0 if pod == "search-svc-2" and i >= 30 and i % 5 == 0 else 90.0 + i % 3

        if query.startswith("avg by (") or query.startswith("max by ("):
            labels_sets = [{"service": "search-svc"}] if " by (service" in query else [{"service": "search-svc", "pod": pod} for pod in pods]
        else:
            labels_sets = [{"__name__": "request_latency_p95", "service": "search-svc", "pod": pod} for pod in pods]
        series = [
            PrometheusSeriesOut(labels=labels, samples=[PrometheusSeriesSample(timestamp=begin + timedelta(minutes=i), value=value(labels.get("pod", "search-svc-2"), i)) for i in range(60)])
            for labels in labels_sets
        ]
        return PrometheusPreviewOut(query=query, start=begin, end=begin + timedelta(hours=1), step="1m", step_seconds=60,
                                    series_count=len(series), sample_count=60 * len(series), series=series, warnings=[])


_PER_POD_RUN = {"query": 'request_latency_p95{service="search-svc"}', "service": "search-svc", "metric": "request_latency_p95",
                "start": "2026-07-26T10:00:00Z", "end": "2026-07-26T11:00:00Z", "step": "1m"}


def test_preview_says_how_to_read_per_pod_series_as_one_line() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = PerPodPrometheusService

    with TestClient(app) as client:
        res = client.post("/api/prometheus/preview", json={k: _PER_POD_RUN[k] for k in ("query", "start", "end", "step")})

    pods = res.json()["pods"]
    assert pods["label"] == "pod"
    assert pods["suggested_combine"] == "avg"
    assert pods["queries"]["avg"] == 'avg by (service) (request_latency_p95{service="search-svc"})'
    assert pods["values"][0] == "search-svc-2"
    assert pods["odd"]["value"] == "search-svc-2"


def test_single_series_preview_has_no_pods() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakePrometheusService(_preview())

    with TestClient(app) as client:
        res = client.post("/api/prometheus/preview", json={"query": "cpu_usage", "start": "2026-07-26T10:00:00Z", "end": "2026-07-26T11:00:00Z", "step": "5m"})

    assert res.json()["pods"] is None


def test_run_without_combine_still_refuses_per_pod_series() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = PerPodPrometheusService

    with TestClient(app) as client:
        res = client.post("/api/analysis/prometheus", json=_PER_POD_RUN)

    assert res.status_code == 400
    assert "which differ by pod" in res.json()["detail"]


def test_run_with_combine_auto_analyzes_the_combined_line() -> None:
    from unittest.mock import patch

    from backend.app.api.ingestion import PreviewPipelineStore
    from intelligence.pipeline import SignalPipeline

    service = PerPodPrometheusService()
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: service

    # A bare SignalPipeline writes to the database in config.yaml.
    with patch("backend.app.api.direct_prometheus.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
        with TestClient(app) as client:
            res = client.post("/api/analysis/prometheus", json={**_PER_POD_RUN, "combine": "auto"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == 'avg by (service) (request_latency_p95{service="search-svc"})'
    assert body["series_count"] == 1
    assert body["combined"]["how"] == "avg"
    assert body["combined"]["count"] == 4
    assert body["combined"]["original_query"] == _PER_POD_RUN["query"]
    assert body["combined"]["odd"]["value"] == "search-svc-2"
    assert service.queries[:2] == [_PER_POD_RUN["query"], body["query"]]


def test_run_with_a_chosen_combine_uses_it() -> None:
    from unittest.mock import patch

    from backend.app.api.ingestion import PreviewPipelineStore
    from intelligence.pipeline import SignalPipeline

    service = PerPodPrometheusService()
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: service

    with patch("backend.app.api.direct_prometheus.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
        with TestClient(app) as client:
            res = client.post("/api/analysis/prometheus", json={**_PER_POD_RUN, "combine": "max"})

    assert res.status_code == 200, res.text
    assert res.json()["combined"]["how"] == "max"
    assert res.json()["query"].startswith("max by (service) (")


class ManyPodsPrometheusService(PerPodPrometheusService):
    """30 pods: more than max_series, so the plain query is refused and only labels can be read."""

    PODS = [f"search-svc-{i}" for i in range(30)]

    def __init__(self):
        super().__init__()
        self.label_reads: list[str] = []

    def preview(self, query: str, start: datetime, end: datetime, step: str):
        self.queries.append(query)
        if not query.startswith(("avg by (", "sum by (", "max by (", "min by (")):
            raise HTTPException(status_code=400, detail="query returned 30 series, which exceeds max_series 20")
        begin = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
        series = [PrometheusSeriesOut(labels={"service": "search-svc"}, samples=[
            PrometheusSeriesSample(timestamp=begin + timedelta(minutes=i), value=90.0 + i % 3) for i in range(60)
        ])]
        return PrometheusPreviewOut(query=query, start=begin, end=begin + timedelta(hours=1), step="1m", step_seconds=60,
                                    series_count=1, sample_count=60, series=series, warnings=[])

    def query_result(self, query: str, **kwargs):
        self.label_reads.append(query)
        return [{"metric": {"__name__": "request_latency_p95", "service": "search-svc", "pod": pod}, "values": []} for pod in self.PODS]


def test_more_pods_than_max_series_are_combined_from_their_labels() -> None:
    from unittest.mock import patch

    from backend.app.api.ingestion import PreviewPipelineStore
    from intelligence.pipeline import SignalPipeline

    service = ManyPodsPrometheusService()
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: service

    with patch("backend.app.api.direct_prometheus.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
        with TestClient(app) as client:
            res = client.post("/api/analysis/prometheus", json={**_PER_POD_RUN, "combine": "auto"})
            refused = client.post("/api/analysis/prometheus", json=_PER_POD_RUN)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == 'avg by (service) (request_latency_p95{service="search-svc"})'
    assert body["combined"]["count"] == 30
    assert body["combined"]["odd"] is None
    assert service.label_reads == [_PER_POD_RUN["query"]]
    # Without combine the query is kept as written, and too many series is still an error.
    assert refused.status_code == 400
    assert "exceeds max_series" in refused.json()["detail"]
