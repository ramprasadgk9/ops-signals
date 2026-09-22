"""Sends a synthetic OTLP metrics export to a running Ops Signals backend, so OTLP ingestion can
be exercised end-to-end through the UI without installing a real OTel Collector.

Usage:
    ./scripts/send_test_otlp_metrics.py
    ./scripts/send_test_otlp_metrics.py --endpoint http://localhost:8001/api/otlp --service checkout
    ./scripts/send_test_otlp_metrics.py --content-type json

The generated series is the same shape as scripts/generate_learning_data.py's known-good pattern
(baseline -> step change -> rising trend, with a few sharp outliers) - not arbitrary noise, since
a flat or purely random series may not cross any analyzer's significance threshold and would
produce nothing to look at in the UI.

Points are timestamped across the last 24h (5-minute spacing) but sent in a single HTTP POST "now"
- exactly how a CSV upload's historical data works too. After sending, either wait up to 60s for
the scheduler's next OTLP backlog cycle, or trigger one immediately (see the printed hint).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from google.protobuf import json_format
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

import urllib.error
import urllib.request

POINT_COUNT = 288
INTERVAL_MINUTES = 5


def _cpu_usage_values() -> list[float]:
    """Same baseline -> step change -> rising trend -> outliers shape as
    scripts/generate_learning_data.py, already known to produce findings in this pipeline."""
    wobble = [0.0, 1.5, -1.2, 2.1, -0.8, 0.6]
    values: list[float] = []
    for i in range(POINT_COUNT):
        if i < 96:
            value = 42 + wobble[i % len(wobble)]
        elif i < 192:
            value = 68 + wobble[i % len(wobble)]
        else:
            value = 70 + ((i - 192) * 0.35) + wobble[i % len(wobble)]
        values.append(value)

    values[130] = 160.0
    values[220] = 12.0
    values[260] = 175.0
    return values


def build_export_request(*, service: str, env: str, host: str) -> ExportMetricsServiceRequest:
    values = _cpu_usage_values()
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=INTERVAL_MINUTES * (POINT_COUNT - 1))

    request = ExportMetricsServiceRequest()
    resource_metrics = request.resource_metrics.add()
    resource_metrics.resource.attributes.extend(
        [
            KeyValue(key="service.name", value=AnyValue(string_value=service)),
            KeyValue(key="deployment.environment", value=AnyValue(string_value=env)),
            KeyValue(key="host.name", value=AnyValue(string_value=host)),
        ]
    )
    scope_metrics = resource_metrics.scope_metrics.add()
    metric = scope_metrics.metrics.add()
    metric.name = "cpu_usage"

    for i, value in enumerate(values):
        timestamp = start + timedelta(minutes=INTERVAL_MINUTES * i)
        data_point = metric.gauge.data_points.add()
        data_point.time_unix_nano = int(timestamp.timestamp() * 1e9)
        data_point.as_double = value

    return request


def send(endpoint: str, request: ExportMetricsServiceRequest, content_type: str) -> None:
    url = endpoint.rstrip("/") + "/v1/metrics"
    if content_type == "json":
        body = json_format.MessageToJson(request).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        body = request.SerializeToString()
        headers = {"Content-Type": "application/x-protobuf"}

    http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=10) as response:
            status = response.status
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        print(f"OTLP export failed: HTTP {exc.code} - {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"Could not reach {url}: {exc.reason}. Is the backend running (./scripts/run_all.sh)?", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"POST {url} -> HTTP {status}")
    if response_body:
        parsed = ExportMetricsServiceResponse()
        try:
            parsed.ParseFromString(response_body)
            if parsed.partial_success.rejected_data_points:
                print(f"  partial_success: {parsed.partial_success.rejected_data_points} point(s) rejected")
                print(f"  reason: {parsed.partial_success.error_message}")
        except Exception:
            pass  # JSON response body, or an unparseable one - the status code already told the story


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default="http://localhost:8001/api/otlp", help="Ops Signals OTLP base endpoint (default: %(default)s)")
    parser.add_argument("--service", default="test-otlp-service", help="service.name resource attribute (default: %(default)s)")
    parser.add_argument("--env", default="local", help="deployment.environment resource attribute (default: %(default)s)")
    parser.add_argument("--host", default="otlp-demo-host-1", help="host.name resource attribute (default: %(default)s)")
    parser.add_argument("--content-type", choices=["protobuf", "json"], default="protobuf")
    args = parser.parse_args()

    request = build_export_request(service=args.service, env=args.env, host=args.host)
    point_count = sum(len(m.gauge.data_points) for rm in request.resource_metrics for sm in rm.scope_metrics for m in sm.metrics)
    print(f"Sending {point_count} cpu_usage points for service='{args.service}' env='{args.env}' host='{args.host}'")

    started = time.perf_counter()
    send(args.endpoint, request, args.content_type)
    print(f"Done in {time.perf_counter() - started:.2f}s")
    print()
    print("Next: the scheduler analyzes buffered OTLP points every 60s. Either wait, or trigger a")
    print("cycle immediately from a shell with the backend's venv active:")
    print("  python3 -c \"from backend.app.autonomous.scheduler import _run_pending_otlp_analysis_once as r; r()\"")
    print(f"Then check the UI (Overview / Findings) filtered to service='{args.service}'.")


if __name__ == "__main__":
    main()
