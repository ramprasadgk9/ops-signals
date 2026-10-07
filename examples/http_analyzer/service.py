"""A minimal HTTP analyzer service, to try the "hosted API or model" path of Add Analyzer.

It follows docs/http-analyzer-contract.md and uses only the Python standard library, so it runs
anywhere Python 3.10+ does:

    python examples/http_analyzer/service.py --port 9100

Then, in Add Analyzer, choose "I have a hosted API or model" and use
    Analyze URL:      http://localhost:9100/analyze
    Health Check URL: http://localhost:9100/health

The detection is deliberately simple (points far from the median, measured in median absolute
deviations). Replace detect() with a call to your own model; keep the request and reply shapes.
"""

from __future__ import annotations

import argparse
import json
import statistics
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def detect(series: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the findings for one series: one per run of consecutive outlying points."""
    threshold = float(params.get("threshold", 6.0))
    points = [(t, v) for t, v in zip(series["timestamps"], series["values"]) if v is not None]
    if len(points) < 10:
        return []
    values = [v for _, v in points]
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values) or 1e-9
    findings: list[dict[str, Any]] = []
    run: list[tuple[str, float, float]] = []
    for timestamp, value in points + [(None, median)]:
        score = abs(value - median) / (1.4826 * mad)
        if timestamp is not None and score >= threshold:
            run.append((timestamp, value, score))
            continue
        if run:
            peak = max(run, key=lambda item: item[2])
            findings.append(
                {
                    "series_id": series["series_id"],
                    "signal_type": "anomaly",
                    "severity": "high" if peak[2] >= threshold * 2 else "medium",
                    "confidence": min(1.0, peak[2] / (threshold * 2)),
                    "start_time": run[0][0],
                    "end_time": run[-1][0],
                    "summary": f"{series['metric_name']} reached {peak[1]:g} against a typical {median:g}.",
                    "evidence": {"max_abs_zscore": round(peak[2], 2), "median": median, "point_count": len(run)},
                }
            )
            run = []
    return findings


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/analyze":
            self._send(404, {"error": "not found"})
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            findings = [
                finding
                for series in request["series"]
                for finding in detect(series, request.get("params") or {})
            ]
        except (KeyError, TypeError, ValueError) as exc:
            self._send(400, {"error": f"bad request: {exc}"})
            return
        self._send(200, {"findings": findings})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"HTTP analyzer listening on http://{args.host}:{args.port}/analyze")
    server.serve_forever()


if __name__ == "__main__":
    main()
