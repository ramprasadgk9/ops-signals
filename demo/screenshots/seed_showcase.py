"""Add showcase data on top of the running demo (docker-compose.demo.yml) for documentation
screenshots: several services with findings, a behavior finding, and cases at different stages.

Everything goes through the public API, using the bundled sample series, so the screenshots show
real analyzer output. Run it once per fresh demo (`docker compose ... down -v` resets):

    python demo/screenshots/seed_showcase.py

Standard library only.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("DEMO_WEB_URL", "http://localhost:8080").rstrip("/")
SERIES = ROOT / "sample_data" / "ops_signals_test_series"

# (sample series, service, metric) - each series was built to show one kind of behavior.
SINGLE_SERIES = [
    ("01_ruptures_abrupt_regime_shift.csv", "payments-api", "cpu_usage"),
    ("04_pyod_adtk_isolated_spikes.csv", "inventory-service", "request_latency_p95"),
    ("02_trend_smooth_linear_increase.csv", "search-api", "memory_usage"),
    ("03_stumpy_repeating_motif.csv", "catalog-api", "http_requests_per_second"),
    ("05_kats_mixed_behavior.csv", "orders-api", "cpu_usage"),
]
# Multi-metric sample (cpu, memory, throttling) that the behavior rules correlate.
BEHAVIOR_SAMPLE = ROOT / "sample_data" / "behavior_test.csv"
BEHAVIOR_SERVICES = ["cart-service"]


def request(method: str, path: str, body: bytes | None = None, content_type: str | None = None):
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        with urlopen(Request(f"{BASE}{path}", data=body, headers=headers, method=method), timeout=300) as response:
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    return json.loads(raw) if raw else None


def send(method: str, path: str, payload: object):
    return request(method, path, json.dumps(payload).encode("utf-8"), "application/json")


def csv_run(file_name: str, csv_text: str, service: str, metric: str) -> str:
    boundary = f"----showcase-{uuid.uuid4().hex}"
    fields = {"provider": "generic", "service": service, "metric_name": metric, "interval": "5m"}
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: text/csv\r\n\r\n".encode()
        + csv_text.encode()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    result = request("POST", "/api/ingestion/csv-run", b"".join(parts), f"multipart/form-data; boundary={boundary}")
    return result["analysis_run_id"]


def single_series_csv(path: Path, service: str, metric: str) -> str:
    """The sample series are timestamp,cpu_usage; the generic provider wants metric_name + value."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["timestamp", "metric_name", "value", "service", "env"])
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            writer.writerow([row["timestamp"], metric, row["cpu_usage"], service, "prod"])
    return out.getvalue()


def top_finding(run_id: str) -> dict | None:
    findings = [f for f in request("GET", f"/api/findings?analysis_run_id={run_id}") if f.get("health_status") != "normal"]
    return findings[0] if findings else None


def main() -> int:
    if any(f["service"] == "payments-api" for f in request("GET", "/api/findings")):
        print("showcase data already present, nothing to do")
        return 0

    runs: dict[str, str] = {}
    for file_name, service, metric in SINGLE_SERIES:
        runs[service] = csv_run(file_name, single_series_csv(SERIES / file_name, service, metric), service, metric)
        print(f"analyzed {file_name} as {service}/{metric}")
    behavior_text = BEHAVIOR_SAMPLE.read_text(encoding="utf-8")
    for service in BEHAVIOR_SERVICES:
        runs[service] = csv_run(BEHAVIOR_SAMPLE.name, behavior_text.replace(",checkout,", f",{service},"), service, "cpu_usage")
        print(f"analyzed {BEHAVIOR_SAMPLE.name} as {service}")

    # Cases at different stages, so the Cases list and Operational Memory aren't all one state.
    stages = [
        ("payments-api", "resolved"),
        ("orders-api", "rca"),
        ("inventory-service", "investigating"),
        ("search-api", "open"),
    ]
    for service, stage in stages:
        finding = top_finding(runs[service])
        if finding is None:
            print(f"no significant finding for {service}, skipping its case")
            continue
        case_id = send("POST", f"/api/cases/findings/{finding['id']}/create", {})["case_id"]
        if stage in {"investigating", "rca", "resolved"}:
            send("PATCH", f"/api/cases/{case_id}/investigation", {
                "investigation_status": "in_progress" if stage == "investigating" else "completed",
                "investigation_note": f"Compared {service} against its last healthy week; the change lines up with the latest rollout.",
            })
        if stage in {"rca", "resolved"}:
            send("PATCH", f"/api/cases/{case_id}/rca", {
                "root_cause_status": "confirmed" if stage == "resolved" else "identified",
                "root_cause_summary": f"A connection-pool limit lowered in the latest {service} release caused request queuing.",
                "root_cause_confidence": 0.8,
                "root_cause_verified": stage == "resolved",
            })
        if stage == "resolved":
            send("PATCH", f"/api/cases/{case_id}/resolution", {
                "outcome_status": "resolved",
                "outcome_summary": "Restored the previous pool size; metrics returned to baseline within 10 minutes.",
                "corrective_action": "Restore the pool size and add a release check for pool settings.",
                "learning_outcome_status": "confirmed",
                "root_cause_category": "configuration change",
                "resolved_by": "oncall",
            })
        print(f"case #{case_id} for {service}: {stage}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
