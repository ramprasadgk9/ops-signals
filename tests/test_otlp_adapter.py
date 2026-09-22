"""Unit tests for OTLP payload flattening and the volume/cardinality guardrails - no HTTP or DB
involved, see tests/api_backend/test_otlp_ingestion.py for the endpoint-level behavior."""

from __future__ import annotations

import time

from google.protobuf import json_format
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from backend.app.otlp.converter import convert_export_request
from backend.app.otlp.limits import CardinalityTracker, RateLimiter


def _resource_metrics(request: ExportMetricsServiceRequest, *, service: str = "payments-api", env: str = "prod"):
    rm = request.resource_metrics.add()
    rm.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value=service)))
    rm.resource.attributes.append(KeyValue(key="deployment.environment", value=AnyValue(string_value=env)))
    return rm.scope_metrics.add()


def test_gauge_and_counter_points_are_flattened_with_resource_attributes() -> None:
    request = ExportMetricsServiceRequest()
    scope_metrics = _resource_metrics(request)

    gauge_metric = scope_metrics.metrics.add()
    gauge_metric.name = "cpu_usage"
    gauge_point = gauge_metric.gauge.data_points.add()
    gauge_point.time_unix_nano = int(time.time() * 1e9)
    gauge_point.as_double = 87.5
    gauge_point.attributes.append(KeyValue(key="host.name", value=AnyValue(string_value="host-1")))

    counter_metric = scope_metrics.metrics.add()
    counter_metric.name = "request_count"
    counter_point = counter_metric.sum.data_points.add()
    counter_point.time_unix_nano = int(time.time() * 1e9)
    counter_point.as_int = 42

    result = convert_export_request(request)

    assert len(result.points) == 2
    assert result.rejected_unsupported_type == 0
    assert result.rejected_missing_value == 0

    gauge = next(p for p in result.points if p.metric_name == "cpu_usage")
    assert gauge.metric_type == "gauge"
    assert gauge.value == 87.5
    assert gauge.service == "payments-api"
    assert gauge.env == "prod"
    assert gauge.host == "host-1"

    counter = next(p for p in result.points if p.metric_name == "request_count")
    assert counter.metric_type == "counter"
    assert counter.value == 42.0


def test_data_point_attributes_override_resource_attributes() -> None:
    request = ExportMetricsServiceRequest()
    scope_metrics = _resource_metrics(request, service="fallback-service")
    metric = scope_metrics.metrics.add()
    metric.name = "cpu_usage"
    point = metric.gauge.data_points.add()
    point.time_unix_nano = int(time.time() * 1e9)
    point.as_double = 1.0
    point.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value="override-service")))

    result = convert_export_request(request)

    assert result.points[0].service == "override-service"


def test_histogram_and_summary_points_are_rejected_not_dropped_silently() -> None:
    request = ExportMetricsServiceRequest()
    scope_metrics = _resource_metrics(request)

    histogram_metric = scope_metrics.metrics.add()
    histogram_metric.name = "latency_histogram"
    for _ in range(3):
        histogram_metric.histogram.data_points.add()

    summary_metric = scope_metrics.metrics.add()
    summary_metric.name = "latency_summary"
    summary_metric.summary.data_points.add()

    result = convert_export_request(request)

    assert result.points == []
    assert result.rejected_unsupported_type == 4


def test_data_point_with_neither_as_double_nor_as_int_is_rejected() -> None:
    request = ExportMetricsServiceRequest()
    scope_metrics = _resource_metrics(request)
    metric = scope_metrics.metrics.add()
    metric.name = "cpu_usage"
    metric.gauge.data_points.add()  # value oneof left unset

    result = convert_export_request(request)

    assert result.points == []
    assert result.rejected_missing_value == 1


def test_json_and_protobuf_encodings_of_the_same_request_convert_identically() -> None:
    request = ExportMetricsServiceRequest()
    scope_metrics = _resource_metrics(request)
    metric = scope_metrics.metrics.add()
    metric.name = "cpu_usage"
    point = metric.gauge.data_points.add()
    point.time_unix_nano = int(time.time() * 1e9)
    point.as_double = 55.0

    from_protobuf = convert_export_request(request)

    json_body = json_format.MessageToJson(request)
    reparsed = ExportMetricsServiceRequest()
    json_format.Parse(json_body, reparsed)
    from_json = convert_export_request(reparsed)

    assert len(from_json.points) == len(from_protobuf.points) == 1
    assert from_json.points[0].value == from_protobuf.points[0].value


def test_rate_limiter_blocks_once_the_per_minute_budget_is_exhausted() -> None:
    limiter = RateLimiter(limit_per_minute=10)

    assert limiter.try_consume(6) is True
    assert limiter.try_consume(5) is False  # 6 + 5 > 10
    assert limiter.try_consume(4) is True  # 6 + 4 == 10, exactly at budget


def test_cardinality_tracker_allows_known_series_but_caps_new_ones() -> None:
    tracker = CardinalityTracker(max_series_per_metric=2)

    assert tracker.allow("cpu_usage", {"host": "a"}) is True
    assert tracker.allow("cpu_usage", {"host": "b"}) is True
    # A third distinct label combination for the same metric exceeds the cap.
    assert tracker.allow("cpu_usage", {"host": "c"}) is False
    # But points for an already-known series are still accepted, even after the cap is hit.
    assert tracker.allow("cpu_usage", {"host": "a"}) is True
    # A different metric name has its own independent budget.
    assert tracker.allow("memory_usage", {"host": "c"}) is True
