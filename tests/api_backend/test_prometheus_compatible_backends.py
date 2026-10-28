"""PrometheusQueryService behaviour that matters on Prometheus-compatible backends (Thanos, Mimir,
VictoriaMetrics, Grafana Cloud): bounded discovery, backend error details, response warnings,
connection-test fallback, and POST for long requests. Only urlopen is faked, so the real request
building and response handling run."""

import io
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous.schemas import AnalysisScope, DiscoveredMetric, MetricDiscoveryResult
from backend.app.autonomous.services import MetricDiscoveryService
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.services import prometheus_service
from backend.app.services.prometheus_service import PrometheusQueryService

BASE_URL = "http://thanos-query:9090"
START = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=24)


class FakeBackend:
    """Records each request and answers from a {path: response} table. A response is a dict
    (JSON body) or an HTTPError to raise."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None, context=None):
        parts = urlsplit(request.full_url)
        body = request.data.decode("utf-8") if request.data else ""
        params = parse_qsl(parts.query) + parse_qsl(body)
        self.requests.append(
            {"method": request.get_method(), "path": parts.path, "params": params, "url": request.full_url}
        )
        response = self.responses.get(parts.path, {"status": "success", "data": []})
        if isinstance(response, HTTPError):
            raise response
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    def for_path(self, path: str) -> list[dict]:
        return [request for request in self.requests if request["path"] == path]


def _http_error(code: int, body: str) -> HTTPError:
    return HTTPError(f"{BASE_URL}/x", code, "error", {}, io.BytesIO(body.encode("utf-8")))


@pytest.fixture
def service() -> PrometheusQueryService:
    return PrometheusQueryService(PrometheusConnectionConfig(base_url=BASE_URL))


def _install(monkeypatch, responses: dict[str, object]) -> FakeBackend:
    backend = FakeBackend(responses)
    monkeypatch.setattr(prometheus_service, "urlopen", backend)
    return backend


def _param(request: dict, name: str) -> list[str]:
    return [value for key, value in request["params"] if key == name]


# 1. Discovery is bounded by a time range


def test_scoped_discovery_sends_the_analysis_window(monkeypatch, service) -> None:
    backend = _install(monkeypatch, {"/api/v1/series": {"status": "success", "data": [{"__name__": "cpu", "service": "checkout"}]}})

    service.discover_metric_metadata(scope_selector='{service="checkout"}', start=START, end=END)

    [series] = backend.for_path("/api/v1/series")
    assert _param(series, "start") == [str(START.timestamp())]
    assert _param(series, "end") == [str(END.timestamp())]


def test_cluster_wide_discovery_sends_the_window_on_label_and_series_lookups(monkeypatch, service) -> None:
    backend = _install(
        monkeypatch,
        {
            "/api/v1/label/__name__/values": {"status": "success", "data": ["cpu", "memory"]},
            "/api/v1/series": {"status": "success", "data": [{"__name__": "cpu"}, {"__name__": "memory"}]},
        },
    )

    service.discover_metric_metadata(start=START, end=END)

    for path in ("/api/v1/label/__name__/values", "/api/v1/series"):
        for request in backend.for_path(path):
            assert _param(request, "start") == [str(START.timestamp())], path
            assert _param(request, "end") == [str(END.timestamp())], path


def test_discovery_without_a_window_sends_no_time_range(monkeypatch, service) -> None:
    backend = _install(monkeypatch, {"/api/v1/label/__name__/values": {"status": "success", "data": ["cpu"]}})

    service.discover_metric_metadata()

    assert all(not _param(request, "start") for request in backend.requests)


def test_preview_api_bounds_discovery_by_the_policy_analysis_window() -> None:
    captured: dict = {}

    class CapturingProvider:
        def discover_metric_metadata(self, **kwargs):
            captured.update(kwargs)
            return MetricDiscoveryResult(metrics=[DiscoveredMetric(metric_name="cpu_usage", labels={"__name__": "cpu_usage"}, service="checkout")])

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: CapturingProvider()
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/preview",
            json={"monitoring_categories": ["capacity"], "execution": {"analysis_window": "6h"}},
        )

    assert response.status_code == 200
    assert captured["end"] - captured["start"] == timedelta(hours=6)


def test_scope_options_api_lists_only_values_seen_in_the_window() -> None:
    calls: list[dict] = []

    class CapturingProvider:
        def label_values(self, label, **kwargs):
            calls.append({"label": label, **kwargs})
            return [f"{label}-a"]

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: CapturingProvider()
    with TestClient(app) as client:
        default = client.get("/api/autonomous/scope-options")
        week = client.get("/api/autonomous/scope-options", params={"window": "7d"})
        invalid = client.get("/api/autonomous/scope-options", params={"window": "soon"})

    assert default.status_code == 200
    assert week.status_code == 200
    assert invalid.status_code == 422
    # services, namespaces, environments and clusters: four windowed lookups per request.
    assert [call["label"] for call in calls[:4]] == ["service", "namespace", "env", "cluster"]
    assert {call["end"] - call["start"] for call in calls[:4]} == {timedelta(hours=24)}
    assert {call["end"] - call["start"] for call in calls[4:]} == {timedelta(days=7)}


# 2. Backend error details are kept


def test_http_error_keeps_the_backends_explanation(monkeypatch, service) -> None:
    body = json.dumps({"status": "error", "errorType": "execution", "error": "the query exceeded the maximum number of series (limit: 10000)"})
    _install(monkeypatch, {"/api/v1/query_range": _http_error(422, body)})

    with pytest.raises(HTTPException) as exc_info:
        service.preview("up", START, START + timedelta(hours=1), "1m")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Prometheus HTTP error: 422: the query exceeded the maximum number of series (limit: 10000)"


def test_http_error_keeps_a_plain_text_explanation(monkeypatch, service) -> None:
    _install(monkeypatch, {"/api/v1/query_range": _http_error(429, "too many outstanding requests")})

    with pytest.raises(HTTPException) as exc_info:
        service.preview("up", START, START + timedelta(hours=1), "1m")

    assert exc_info.value.detail == "Prometheus HTTP error: 429: too many outstanding requests"


def test_http_error_does_not_echo_an_html_error_page(monkeypatch, service) -> None:
    _install(monkeypatch, {"/api/v1/query_range": _http_error(502, "<html><body>Bad Gateway</body></html>")})

    with pytest.raises(HTTPException) as exc_info:
        service.preview("up", START, START + timedelta(hours=1), "1m")

    assert exc_info.value.detail == "Prometheus HTTP error: 502"


# 3. Response warnings reach the caller


def test_range_query_warnings_are_returned_with_the_preview(monkeypatch, service) -> None:
    _install(
        monkeypatch,
        {
            "/api/v1/query_range": {
                "status": "success",
                "warnings": ["No StoreAPIs matched for this query"],
                "data": {"resultType": "matrix", "result": [{"metric": {"__name__": "up"}, "values": [[START.timestamp(), "1"]]}]},
            }
        },
    )

    preview = service.preview("up", START, START + timedelta(hours=1), "1m")

    assert preview.warnings == ["Prometheus warning: No StoreAPIs matched for this query"]


def test_discovery_warnings_reach_the_resolved_scope(monkeypatch, service) -> None:
    _install(
        monkeypatch,
        {
            "/api/v1/series": {
                "status": "success",
                "warnings": ["partial response: store unavailable"],
                "data": [{"__name__": "cpu", "service": "checkout"}],
            }
        },
    )

    resolved, _ = MetricDiscoveryService(service).discover(
        AnalysisScope(services=["checkout"], all_services=False), start=START, end=END
    )

    assert "Prometheus warning: partial response: store unavailable" in resolved.warnings


# 4. Connection test falls back when buildinfo is not served


def test_connection_test_falls_back_when_buildinfo_is_not_served(monkeypatch, service) -> None:
    backend = _install(
        monkeypatch,
        {
            "/api/v1/status/buildinfo": _http_error(404, "404 page not found"),
            "/api/v1/query": {"status": "success", "data": {"resultType": "vector", "result": []}},
        },
    )

    ok, version, _, message = service.test_connection()

    assert ok is True
    assert version is None
    assert message == "Connection successful (server version unavailable)"
    assert _param(backend.for_path("/api/v1/query")[0], "query") == ["vector(1)"]


def test_connection_test_reports_auth_failures_without_falling_back(monkeypatch, service) -> None:
    backend = _install(monkeypatch, {"/api/v1/status/buildinfo": _http_error(401, "unauthorized")})

    ok, _, _, message = service.test_connection()

    assert ok is False
    assert message == "Prometheus HTTP error: 401: unauthorized"
    assert backend.for_path("/api/v1/query") == []


def test_connection_test_fails_when_the_fallback_query_fails(monkeypatch, service) -> None:
    _install(
        monkeypatch,
        {
            "/api/v1/status/buildinfo": _http_error(404, "not found"),
            "/api/v1/query": _http_error(404, "not found"),
        },
    )

    ok, _, _, _ = service.test_connection()

    assert ok is False


# 5. Long requests are sent as POST


def test_short_series_lookup_stays_a_get(monkeypatch, service) -> None:
    backend = _install(monkeypatch, {})

    service.direct_scoped_series('{service="checkout"}', start=START, end=END)

    [request] = backend.for_path("/api/v1/series")
    assert request["method"] == "GET"


def test_long_series_lookup_is_sent_as_a_post_form(monkeypatch, service) -> None:
    backend = _install(monkeypatch, {})
    metric_names = [f"some_reasonably_long_metric_name_{index}_seconds_total" for index in range(80)]

    service.series_metadata(metric_names, scope_selector='{namespace="payments"}', start=START, end=END)

    [request] = backend.for_path("/api/v1/series")
    assert request["method"] == "POST"
    assert "?" not in request["url"]
    assert len(_param(request, "match[]")) == 80
    assert _param(request, "match[]")[0] == '{namespace="payments",__name__="some_reasonably_long_metric_name_0_seconds_total"}'
    assert _param(request, "start") == [str(START.timestamp())]


def test_label_values_are_never_posted(monkeypatch, service) -> None:
    """Prometheus only serves /api/v1/label/<name>/values over GET."""
    backend = _install(monkeypatch, {"/api/v1/label/service/values": {"status": "success", "data": []}})

    service.label_values("service", matchers=['{namespace="' + "x" * 3000 + '"}'])

    [request] = backend.for_path("/api/v1/label/service/values")
    assert request["method"] == "GET"


# 6. Series lists are bounded, and a metric with very many series doesn't hide the others


class SeriesServer(FakeBackend):
    """Serves /api/v1/series and the __name__ label values from a list of series, filtering by the
    __name__ in each match[] and, like Prometheus 2.54 and Mimir 2.17, returning at most `limit`
    series sorted by labels (unless honor_limit is False, like an older server)."""

    def __init__(self, series: list[dict[str, str]], *, honor_limit: bool = True, fail_scoped: HTTPError | None = None):
        super().__init__({})
        self.series = sorted(series, key=lambda labels: sorted(labels.items()))
        self.honor_limit = honor_limit
        self.fail_scoped = fail_scoped
        self.largest_answer = 0

    def __call__(self, request, timeout=None, context=None):
        response = super().__call__(request, timeout, context)
        params = self.requests[-1]["params"]
        path = self.requests[-1]["path"]
        if path == "/api/v1/label/__name__/values":
            return self._answer({"status": "success", "data": sorted({labels["__name__"] for labels in self.series})})
        if path != "/api/v1/series":
            return response
        names = {matcher.split('__name__="')[1].rstrip('"}') for key, matcher in params if key == "match[]" and "__name__" in matcher}
        if not names and self.fail_scoped is not None:
            raise self.fail_scoped
        rows = [labels for labels in self.series if not names or labels["__name__"] in names]
        limit = int(dict(params).get("limit", 0))
        payload: dict[str, object] = {"status": "success", "data": rows}
        if self.honor_limit and limit and len(rows) > limit:
            payload = {"status": "success", "data": rows[:limit], "warnings": ["results truncated due to limit"]}
        self.largest_answer = max(self.largest_answer, len(payload["data"]))
        return self._answer(payload)

    @staticmethod
    def _answer(payload: dict) -> io.BytesIO:
        return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _checkout_series(hot_series: int) -> list[dict[str, str]]:
    """checkout_api_calls has one series per user; four ordinary metrics have three pods each."""
    rows = [{"__name__": "checkout_api_calls", "service": "checkout", "user_id": f"u{index:05d}"} for index in range(hot_series)]
    for name in ("checkout_cpu", "checkout_errors", "checkout_latency", "checkout_memory"):
        rows.extend({"__name__": name, "service": "checkout", "pod": f"pod-{index}"} for index in range(3))
    return rows


def _found(result: MetricDiscoveryResult) -> set[str]:
    return {metric.metric_name for metric in result.metrics}


def test_small_scope_is_listed_in_one_request_as_before(monkeypatch, service) -> None:
    server = SeriesServer(_checkout_series(hot_series=3))
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    result = service.discover_metric_metadata(scope_selector='{service="checkout"}', start=START, end=END)

    [request] = server.for_path("/api/v1/series")
    assert _param(request, "limit") == ["5001"]
    assert _found(result) == {"checkout_api_calls", "checkout_cpu", "checkout_errors", "checkout_latency", "checkout_memory"}
    assert result.series_available == 15
    assert result.warnings == []


def test_metric_with_very_many_series_does_not_hide_the_others(monkeypatch, service) -> None:
    server = SeriesServer(_checkout_series(hot_series=1000))
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    result = service.discover_metric_metadata(scope_selector='{service="checkout"}', limit=20, start=START, end=END)

    assert _found(result) == {"checkout_api_calls", "checkout_cpu", "checkout_errors", "checkout_latency", "checkout_memory"}
    assert result.starved_metrics == []
    assert server.largest_answer <= 21
    assert result.series_available is None
    assert result.truncated is False
    assert result.warnings == [
        "Very many series: checkout_api_calls (at least 21 series). This is usually a label with a value per user, "
        "request or pod. Every metric was still found, but dropping that label (relabeling) makes these metrics "
        "cheaper to store and query."
    ]


def test_metrics_the_cut_off_list_never_reached_are_asked_for_one_at_a_time(monkeypatch, service) -> None:
    server = SeriesServer(_checkout_series(hot_series=1000))
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    service.discover_metric_metadata(scope_selector='{service="checkout"}', limit=20, start=START, end=END)

    single = [request for request in server.for_path("/api/v1/series") if len(_param(request, "match[]")) == 1 and "__name__" in _param(request, "match[]")[0]]
    assert sorted(_param(request, "match[]")[0] for request in single) == [
        '{service="checkout",__name__="checkout_cpu"}',
        '{service="checkout",__name__="checkout_errors"}',
        '{service="checkout",__name__="checkout_latency"}',
        '{service="checkout",__name__="checkout_memory"}',
    ]
    assert {_param(request, "limit")[0] for request in single} == {"4"}


def test_server_that_ignores_limit_still_finds_every_metric(monkeypatch, service) -> None:
    server = SeriesServer(_checkout_series(hot_series=1000), honor_limit=False)
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    result = service.discover_metric_metadata(scope_selector='{service="checkout"}', limit=20, start=START, end=END)

    assert _found(result) == {"checkout_api_calls", "checkout_cpu", "checkout_errors", "checkout_latency", "checkout_memory"}
    assert result.starved_metrics == []


def test_cluster_wide_discovery_is_bounded_too(monkeypatch, service) -> None:
    server = SeriesServer(_checkout_series(hot_series=1000))
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    result = service.discover_metric_metadata(limit=20, start=START, end=END)

    assert len(_found(result)) == 5
    assert server.largest_answer <= 21


def test_failed_scoped_listing_is_explained_and_discovery_carries_on(monkeypatch, service) -> None:
    refusal = _http_error(500, json.dumps({"status": "error", "error": "rpc error: code = ResourceExhausted desc = grpc: received message larger than max (382555560 vs. 104857600)"}))
    server = SeriesServer(_checkout_series(hot_series=3), fail_scoped=refusal)
    monkeypatch.setattr(prometheus_service, "urlopen", server)

    result = service.discover_metric_metadata(scope_selector='{service="checkout"}', start=START, end=END)

    assert len(_found(result)) == 5
    [warning] = result.warnings
    assert warning.startswith(
        "Listing this scope's series in one request failed (Prometheus HTTP error: 500: the answer was larger than "
        "the server sends in one response; narrow the scope or the query (rpc error:"
    )
    assert warning.endswith("Ops Signals listed them metric by metric instead.")


def test_dropped_connection_is_a_clear_503(monkeypatch, service) -> None:
    from http.client import RemoteDisconnected

    def drop(request, timeout=None, context=None):
        raise RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr(prometheus_service, "urlopen", drop)

    with pytest.raises(HTTPException) as exc_info:
        service.preview("up", START, START + timedelta(hours=1), "1m")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Prometheus connection failed"
