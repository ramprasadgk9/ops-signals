"""Flattens an OTLP ExportMetricsServiceRequest into plain point records.

Scope: Gauge and Sum (counter) metrics only, per docs/otlp-metrics-ingestion-plan.md §2.
Histogram, ExponentialHistogram, and Summary points are counted and rejected here rather than
silently dropped or crashed on - the caller reports the count back to the sender via the OTLP
response's partial_success field, which is the spec-intended way to say "received but not fully
processed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import ResourceMetrics


@dataclass(slots=True)
class OtlpPoint:
    metric_name: str
    metric_type: str  # "gauge" or "counter"
    timestamp: datetime
    value: float
    service: str
    env: str | None
    host: str | None
    namespace: str | None
    pod: str | None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class OtlpConversionResult:
    points: list[OtlpPoint]
    rejected_unsupported_type: int = 0
    rejected_missing_value: int = 0


def _decode_any_value(value: AnyValue) -> str | None:
    kind = value.WhichOneof("value")
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return str(value.bool_value)
    if kind == "int_value":
        return str(value.int_value)
    if kind == "double_value":
        return str(value.double_value)
    # array_value / kvlist_value / bytes_value: not flattened into a scalar tag - rare for
    # resource/data-point attributes and not needed for the canonical schema's tags_json.
    return None


def _attributes_to_dict(attributes: list[KeyValue]) -> dict[str, str]:
    result: dict[str, str] = {}
    for kv in attributes:
        decoded = _decode_any_value(kv.value)
        if decoded is not None:
            result[kv.key] = decoded
    return result


def _resource_context(resource_metrics: ResourceMetrics) -> tuple[dict[str, str], str, str | None, str | None, str | None, str | None]:
    resource_attrs = _attributes_to_dict(resource_metrics.resource.attributes)
    service = resource_attrs.get("service.name") or "unknown-service"
    env = resource_attrs.get("deployment.environment") or resource_attrs.get("deployment.environment.name")
    host = resource_attrs.get("host.name")
    namespace = resource_attrs.get("k8s.namespace.name")
    pod = resource_attrs.get("k8s.pod.name")
    return resource_attrs, service, env, host, namespace, pod


def convert_export_request(request: ExportMetricsServiceRequest) -> OtlpConversionResult:
    points: list[OtlpPoint] = []
    rejected_unsupported_type = 0
    rejected_missing_value = 0

    for resource_metrics in request.resource_metrics:
        resource_attrs, service, env, host, namespace, pod = _resource_context(resource_metrics)

        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                kind = metric.WhichOneof("data")

                if kind == "gauge":
                    data_points = metric.gauge.data_points
                    metric_type = "gauge"
                elif kind == "sum":
                    data_points = metric.sum.data_points
                    metric_type = "counter"
                elif kind == "histogram":
                    rejected_unsupported_type += len(metric.histogram.data_points)
                    continue
                elif kind == "exponential_histogram":
                    rejected_unsupported_type += len(metric.exponential_histogram.data_points)
                    continue
                elif kind == "summary":
                    rejected_unsupported_type += len(metric.summary.data_points)
                    continue
                else:
                    continue

                for data_point in data_points:
                    value_kind = data_point.WhichOneof("value")
                    if value_kind == "as_double":
                        value = data_point.as_double
                    elif value_kind == "as_int":
                        value = float(data_point.as_int)
                    else:
                        rejected_missing_value += 1
                        continue

                    dp_attrs = _attributes_to_dict(data_point.attributes)
                    merged_attrs = {**resource_attrs, **dp_attrs}

                    points.append(
                        OtlpPoint(
                            metric_name=metric.name,
                            metric_type=metric_type,
                            timestamp=datetime.fromtimestamp(data_point.time_unix_nano / 1e9, tz=timezone.utc),
                            value=value,
                            service=dp_attrs.get("service.name") or service,
                            env=dp_attrs.get("deployment.environment") or env,
                            host=dp_attrs.get("host.name") or host,
                            namespace=dp_attrs.get("k8s.namespace.name") or namespace,
                            pod=dp_attrs.get("k8s.pod.name") or pod,
                            attributes=merged_attrs,
                        )
                    )

    return OtlpConversionResult(
        points=points,
        rejected_unsupported_type=rejected_unsupported_type,
        rejected_missing_value=rejected_missing_value,
    )
