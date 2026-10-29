"""Pushes the orders service's metrics to Ops Signals over OTLP/HTTP, the way an OpenTelemetry
Collector would (docker-compose.demo.yml: demo-otlp).

On first start it sends the last 6.5h in batches, so the backend has a history to compare against,
then one point per series every 30s. The failed-orders counter is cumulative, as OTel SDKs send it;
Ops Signals turns it into a per-second rate. OTLP JSON over plain HTTP: standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenario  # noqa: E402

ENDPOINT = os.environ.get("DEMO_OTLP_ENDPOINT", "http://backend:8000/api/otlp/v1/metrics")
STATE_DIR = Path(os.environ.get("DEMO_STATE_DIR", "/demo-state"))
BACKFILLED_FILE = "otlp-backfilled"
BATCH_POINTS = 240  # per series, per request


def log(message: str) -> None:
    print(f"demo-otlp: {message}", flush=True)


def _attribute(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def export_request(times: list[float], at: dict[str, float]) -> dict[str, object]:
    """One OTLP ExportMetricsServiceRequest with a point per series at each of `times`."""
    start = at["orders_history_start"]
    start_nanos = str(int(start * 1e9))
    failed = [
        {"startTimeUnixNano": start_nanos, "timeUnixNano": str(int(t * 1e9)),
         "asInt": str(scenario.orders_failed_total(t, start, at["orders_shift_at"]))}
        for t in times
    ]
    duration = [
        {"timeUnixNano": str(int(t * 1e9)), "asDouble": scenario.orders_processing_seconds(t, at["orders_slow_at"])}
        for t in times
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", scenario.ORDERS_SERVICE),
                        _attribute("deployment.environment", scenario.ENV),
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "ops-signals-demo"},
                        "metrics": [
                            {
                                "name": scenario.ORDERS_FAILED_METRIC,
                                "description": "orders that failed to complete",
                                "unit": "1",
                                "sum": {
                                    "dataPoints": failed,
                                    "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
                                    "isMonotonic": True,
                                },
                            },
                            {
                                "name": scenario.ORDERS_DURATION_METRIC,
                                "description": "time to process one order",
                                "unit": "s",
                                "gauge": {"dataPoints": duration},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def send(times: list[float], at: dict[str, float]) -> None:
    body = json.dumps(export_request(times, at)).encode("utf-8")
    request = Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        response.read()


def send_with_retry(times: list[float], at: dict[str, float], attempts: int = 60) -> None:
    for attempt in range(attempts):
        try:
            send(times, at)
            return
        except HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError(f"OTLP export rejected: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')}") from exc
            reason = f"HTTP {exc.code}"
        except (URLError, ConnectionError, OSError) as exc:
            reason = str(exc)
        if attempt == 0 or attempt % 10 == 9:
            log(f"backend not taking OTLP yet ({reason}), retrying")
        time.sleep(5)
    raise RuntimeError(f"OTLP export failed after {attempts} attempts")


def main() -> int:
    timeline = None
    while timeline is None:
        timeline = scenario.read_timeline(STATE_DIR)
        if timeline is None:
            time.sleep(2)
    at = {key: scenario.parse_time(value).timestamp() for key, value in timeline.items()}
    start = at["orders_history_start"]
    step = scenario.ORDERS_STEP_SECONDS

    marker = STATE_DIR / BACKFILLED_FILE
    now = time.time()
    if not marker.exists():
        times = [float(t) for t in range(int(start), int(now), step)]
        for index in range(0, len(times), BATCH_POINTS):
            send_with_retry(times[index : index + BATCH_POINTS], at)
        marker.write_text(f"{len(times)}\n", encoding="utf-8")
        log(f"sent {len(times)} points of {scenario.ORDERS_SERVICE} history per series")
    else:
        log("history already sent; continuing live")

    log(f"sending {scenario.ORDERS_SERVICE} metrics every {step}s to {ENDPOINT}")
    while True:
        time.sleep(step)
        try:
            send_with_retry([time.time()], at, attempts=3)
        except RuntimeError as exc:
            log(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
