"""Live Prometheus scrape target for the demo: continues the backfilled checkout-api series from
where the history ends (docker-compose.demo.yml: demo-metrics)."""

from __future__ import annotations

import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenario  # noqa: E402

STATE_DIR = Path(os.environ.get("DEMO_STATE_DIR", "/demo-state"))
PORT = int(os.environ.get("DEMO_METRICS_PORT", "9102"))


def _shift_at() -> float | None:
    timeline = scenario.read_timeline(STATE_DIR)
    # No timeline yet (history not written): serve the post-shift level, which is what "now" looks like.
    return scenario.parse_time(timeline["shift_at"]).timestamp() if timeline else None


def render(now: float) -> str:
    series_labels = scenario.format_labels(scenario.labels())
    return "\n".join(
        [
            f"# HELP {scenario.LATENCY_METRIC} p95 request latency in milliseconds",
            f"# TYPE {scenario.LATENCY_METRIC} gauge",
            f"{scenario.LATENCY_METRIC}{{{series_labels}}} {scenario.latency_ms(now, _shift_at()):.3f}",
            f"# HELP {scenario.RPS_METRIC} requests per second",
            f"# TYPE {scenario.RPS_METRIC} gauge",
            f"{scenario.RPS_METRIC}{{{series_labels}}} {scenario.rps(now):.3f}",
            "",
        ]
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/metrics":
            body = render(time.time()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
        elif self.path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        else:
            body = b"not found\n"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # one line per scrape is noise


if __name__ == "__main__":
    print(f"demo-metrics: serving {scenario.SERVICE} metrics on :{PORT}/metrics", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
