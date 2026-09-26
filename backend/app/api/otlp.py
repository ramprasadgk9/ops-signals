"""OTLP/HTTP metrics receiver.

POST /api/otlp/v1/metrics - not the OTLP-spec-default root path /v1/metrics, because
docker/nginx.web.conf only proxies /api/ to the backend and every other route in this app already
lives under /api/*. Still spec-compliant: an OTel Collector's otlphttp exporter accepts an
explicit `endpoint: http://<host>:<port>/api/otlp` and auto-appends /v1/metrics itself. See
docs/design/otlp-metrics-ingestion-plan.md §3.

Scope: metrics only (Gauge/Sum), OTLP/HTTP only (protobuf and JSON bodies), store-then-analyze-on-
a-timer rather than per-request analysis - see docs/design/otlp-metrics-ingestion-plan.md §2 for why.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from google.protobuf import json_format
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceResponse
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)

from backend.app.models.db import get_session_local
from backend.app.models.entities import OtlpPendingPointEntity
from backend.app.otlp.converter import OtlpPoint, convert_export_request
from backend.app.otlp.limits import MAX_OTLP_BYTES, cardinality_tracker, rate_limiter
from backend.app.otlp.metrics import OTLP_POINTS_RECEIVED_TOTAL, OTLP_POINTS_REJECTED_TOTAL
from backend.app.otlp.metrics import snapshot as otlp_metrics_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/otlp", tags=["otlp"])

_JSON_CONTENT_TYPE = "application/json"
_PROTOBUF_CONTENT_TYPE = "application/x-protobuf"


@router.get("/status")
async def otlp_status() -> dict[str, object]:
    """Plain-JSON summary for the Settings page's OTLP card - the passive "is data arriving"
    signal that has no active-test equivalent the way Prometheus's Test Connection does, since
    Ops Signals never initiates an OTLP connection (see docs/design/otlp-metrics-ingestion-plan.md §3)."""
    return {"endpoint_path": "/api/otlp/v1/metrics", **otlp_metrics_snapshot()}


@router.post("/v1/metrics")
async def export_metrics(request: Request) -> Response:
    body = await request.body()
    if len(body) > MAX_OTLP_BYTES:
        return Response(
            content=(
                f"request body of {len(body)} bytes exceeds the configured limit of "
                f"{MAX_OTLP_BYTES} bytes (set OPS_SIGNALS_MAX_OTLP_BYTES to change)"
            ),
            status_code=413,
        )

    is_json = _is_json_request(request)
    export_request = ExportMetricsServiceRequest()
    try:
        if is_json:
            json_format.Parse(body, export_request)
        else:
            export_request.ParseFromString(body)
    except (DecodeError, json_format.ParseError) as exc:
        return Response(content=f"malformed OTLP metrics payload: {exc}", status_code=400)

    conversion = convert_export_request(export_request)

    if conversion.points and not rate_limiter.try_consume(len(conversion.points)):
        OTLP_POINTS_REJECTED_TOTAL.labels(reason="rate_limit").inc(len(conversion.points))
        return Response(
            content=(
                f"OTLP ingestion rate limit exceeded (max {rate_limiter.limit_per_minute} "
                "points/min; set OPS_SIGNALS_OTLP_MAX_POINTS_PER_MIN to change); retry after "
                "backing off"
            ),
            status_code=429,
            headers={"Retry-After": "30"},
        )

    accepted: list[OtlpPoint] = []
    rejected_cardinality = 0
    for point in conversion.points:
        if cardinality_tracker.allow(point.metric_name, point.attributes):
            accepted.append(point)
        else:
            rejected_cardinality += 1

    if accepted:
        _persist_pending_points(accepted)
        OTLP_POINTS_RECEIVED_TOTAL.inc(len(accepted))
    if conversion.rejected_unsupported_type:
        OTLP_POINTS_REJECTED_TOTAL.labels(reason="unsupported_type").inc(conversion.rejected_unsupported_type)
    if conversion.rejected_missing_value:
        OTLP_POINTS_REJECTED_TOTAL.labels(reason="missing_value").inc(conversion.rejected_missing_value)
    if rejected_cardinality:
        OTLP_POINTS_REJECTED_TOTAL.labels(reason="cardinality_limit").inc(rejected_cardinality)

    total_rejected = conversion.rejected_unsupported_type + conversion.rejected_missing_value + rejected_cardinality
    response_proto = ExportMetricsServiceResponse()
    if total_rejected:
        response_proto.partial_success.rejected_data_points = total_rejected
        response_proto.partial_success.error_message = _rejection_summary(
            unsupported_type=conversion.rejected_unsupported_type,
            missing_value=conversion.rejected_missing_value,
            cardinality_limit=rejected_cardinality,
        )
        logger.info(
            "OTLP export: accepted=%d rejected=%d (unsupported_type=%d missing_value=%d cardinality_limit=%d)",
            len(accepted),
            total_rejected,
            conversion.rejected_unsupported_type,
            conversion.rejected_missing_value,
            rejected_cardinality,
        )

    return _respond(is_json, response_proto)


def _is_json_request(request: Request) -> bool:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    return content_type == _JSON_CONTENT_TYPE


def _respond(is_json: bool, response_proto: ExportMetricsServiceResponse) -> Response:
    if is_json:
        return Response(
            content=json_format.MessageToJson(response_proto),
            status_code=200,
            media_type=_JSON_CONTENT_TYPE,
        )
    return Response(
        content=response_proto.SerializeToString(),
        status_code=200,
        media_type=_PROTOBUF_CONTENT_TYPE,
    )


def _rejection_summary(*, unsupported_type: int, missing_value: int, cardinality_limit: int) -> str:
    parts = []
    if unsupported_type:
        parts.append(f"{unsupported_type} point(s) used an unsupported metric type (histogram/summary)")
    if missing_value:
        parts.append(f"{missing_value} point(s) had no numeric value")
    if cardinality_limit:
        parts.append(f"{cardinality_limit} point(s) exceeded the configured series-per-metric cardinality limit")
    return "; ".join(parts)


def _persist_pending_points(points: list[OtlpPoint]) -> None:
    session_local = get_session_local()
    with session_local() as db:
        db.bulk_save_objects(
            [
                OtlpPendingPointEntity(
                    metric_name=point.metric_name,
                    metric_type=point.metric_type,
                    timestamp=point.timestamp,
                    value=point.value,
                    service=point.service,
                    env=point.env,
                    host=point.host,
                    namespace=point.namespace,
                    pod=point.pod,
                    attributes_json=point.attributes,
                )
                for point in points
            ]
        )
        db.commit()
