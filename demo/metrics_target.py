"""Live Prometheus scrape target for the demo: continues every backfilled series from where the
history ends (docker-compose.demo.yml: demo-metrics)."""

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

_series: list[scenario.Series] | None = None


def _all_series() -> list[scenario.Series]:
    global _series
    if _series is None:
        # demo-history writes the timeline before this container starts (depends_on in compose).
        timeline = scenario.read_timeline(STATE_DIR) or scenario.new_timeline()
        _series = scenario.prometheus_series(timeline)
    return _series


def render(now: float) -> str:
    lines: list[str] = []
    family = None
    for series in _all_series():
        value = series.value_at(now)
        if value is None:
            continue
        if series.name != family:
            family = series.name
            lines += [f"# HELP {family} {series.help}", f"# TYPE {family} gauge"]
        lines.append(f"{series.name}{{{scenario.format_labels(series.labels)}}} {value:.4f}")
    return "\n".join(lines) + "\n"


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
    print(f"demo-metrics: serving {len(_all_series())} demo series on :{PORT}/metrics", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
