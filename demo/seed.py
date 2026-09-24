"""One-shot: seed the demo story through the public API, then exit (docker-compose.demo.yml:
demo-seeder). Alertmanager only starts after this succeeds, so the alert always lands on a fully
seeded backend.

1. Change events: today's deploy v2.14.0, yesterday's v2.13.2, and v2.9.0 three weeks ago.
2. A past incident: analyze a CSV of the v2.9.0 latency shift, open a case from its finding, record
   the root cause and the rollback that fixed it, and index it into operational memory.
3. Move that past incident's rows back to when it happened. The API stamps everything "now", which
   would make a three-week-old incident look like it happened a minute ago (and alert enrichment
   would reuse its finding as today's analysis).

The alert itself comes from the real path: a Prometheus rule fires, Alertmanager routes it to
/api/integrations/alertmanager, and the backend enriches it and posts to the Slack sink.

Idempotent via a marker file in the demo state volume.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenario  # noqa: E402

BACKEND = os.environ.get("DEMO_BACKEND_URL", "http://backend:8000").rstrip("/")
STATE_DIR = Path(os.environ.get("DEMO_STATE_DIR", "/demo-state"))
SEEDED_FILE = "seeded.json"
WEB_URL = os.environ.get("DEMO_WEB_URL", "http://localhost:8080")
SLACK_SINK_URL = os.environ.get("DEMO_SLACK_SINK_URL", "http://localhost:8090")


def log(message: str) -> None:
    print(f"demo-seeder: {message}", flush=True)


# --- HTTP ---------------------------------------------------------------------------------------


def _request(method: str, path: str, body: bytes | None = None, content_type: str | None = None, timeout: float = 300):
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(f"{BACKEND}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else None


def get(path: str):
    return _request("GET", path)


def send(method: str, path: str, payload: object):
    return _request(method, path, json.dumps(payload).encode("utf-8"), "application/json")


def post_csv(path: str, file_name: str, csv_text: str, fields: dict[str, str]):
    boundary = f"----ops-signals-demo-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode("utf-8")
        + csv_text.encode("utf-8")
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return _request("POST", path, b"".join(parts), f"multipart/form-data; boundary={boundary}")


def wait_for_backend(timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            health = get("/api/memory/health")
            # Memory health reports on Qdrant + the embedder; the similar-case search needs both.
            if isinstance(health, dict) and health.get("enabled") and health.get("status") == "healthy":
                return
            last_error = f"memory not ready: {health}"
        except (URLError, ConnectionError, OSError, RuntimeError) as exc:
            last_error = str(exc)
        time.sleep(3)
    raise RuntimeError(f"backend not ready after {timeout_seconds}s: {last_error}")


# --- seeding steps ------------------------------------------------------------------------------


def seed_change_events(timeline: dict[str, str], past: dict[str, datetime]) -> None:
    base = {"service": scenario.SERVICE, "type": "deploy", "env": scenario.ENV, "source": "github-actions"}
    events = [
        {
            **base,
            "timestamp": past["deploy_at"].isoformat(),
            "version": scenario.PAST_DEPLOY_VERSION,
            "author": "maya",
            "description": "Switch checkout pricing lookups to the new catalog client",
        },
        {
            **base,
            "timestamp": timeline["previous_deploy_at"],
            "version": scenario.PREVIOUS_DEPLOY_VERSION,
            "author": "dev-bot",
            "description": "Dependency bumps",
        },
        {
            **base,
            "timestamp": timeline["deploy_at"],
            "version": scenario.CURRENT_DEPLOY_VERSION,
            "author": "alex",
            "description": "Enable per-item tax calculation in checkout",
        },
    ]
    # A seeder run that failed halfway may already have recorded some of these.
    existing = {event.get("version") for event in get(f"/api/events?service={scenario.SERVICE}&limit=500")}
    events = [event for event in events if event["version"] not in existing]
    if events:
        send("POST", "/api/events", events)
    log(f"recorded {len(events)} deploy events (current: {scenario.CURRENT_DEPLOY_VERSION} at {timeline['deploy_at']})")


def seed_past_incident(anchor: datetime) -> dict[str, object]:
    run = post_csv(
        "/api/ingestion/csv-run",
        "checkout-api-latency-incident.csv",
        scenario.past_incident_csv(anchor),
        {
            "provider": "generic",
            "service": scenario.SERVICE,
            "metric_name": scenario.LATENCY_METRIC,
            "interval": "30s",
        },
    )
    run_id = run["analysis_run_id"]
    findings = [
        finding
        for finding in get(f"/api/findings?analysis_run_id={run_id}")
        if finding.get("health_status") != "normal"
    ]
    if not findings:
        raise RuntimeError(f"past-incident analysis {run_id} produced no significant finding")
    finding = findings[0]  # the API returns them by importance, highest first
    log(f"past incident analyzed: {finding['title']!r} (finding #{finding['id']})")

    case = send("POST", f"/api/cases/findings/{finding['id']}/create", {})
    case_id = case["case_id"]
    send(
        "PATCH",
        f"/api/cases/{case_id}/investigation",
        {
            "investigation_status": "completed",
            "investigation_note": (
                f"p95 latency on {scenario.SERVICE} stepped from ~175ms to ~310ms four minutes after "
                f"deploy {scenario.PAST_DEPLOY_VERSION}. Traces show every checkout request making "
                "an extra synchronous call to the catalog service for pricing."
            ),
        },
    )
    send(
        "PATCH",
        f"/api/cases/{case_id}/rca",
        {
            "root_cause_status": "confirmed",
            "root_cause_summary": (
                f"Deploy {scenario.PAST_DEPLOY_VERSION} added a synchronous per-item catalog lookup to "
                "the checkout request path, raising p95 latency by ~130ms."
            ),
            "root_cause_confidence": 0.9,
            "root_cause_verified": True,
        },
    )
    send(
        "PATCH",
        f"/api/cases/{case_id}/resolution",
        {
            "outcome_status": "resolved",
            "outcome_summary": (
                f"Rolled back {scenario.PAST_DEPLOY_VERSION}; p95 latency returned to baseline within 5 minutes."
            ),
            "corrective_action": "Roll back the deploy, then batch the catalog lookups before re-releasing.",
            "learning_outcome_status": "confirmed",
            "root_cause_category": "deploy regression",
            "resolved_by": "oncall",
        },
    )
    log(f"past case #{case_id} resolved (rollback of {scenario.PAST_DEPLOY_VERSION})")
    return {"analysis_run_id": run_id, "case_id": case_id, "finding_id": finding["id"]}


def backdate_past_incident(past: dict[str, object], times: dict[str, datetime]) -> None:
    from sqlalchemy import create_engine, text

    url = os.environ["OPS_INTEL_DATABASE_URL"]
    run_id, case_id = past["analysis_run_id"], past["case_id"]
    detected, resolved = times["detected_at"], times["resolved_at"]
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE analysis_runs SET created_at = :t WHERE id = :run"), {"t": detected, "run": run_id})
        for table in ("ops_operational_signals", "ops_operational_findings"):
            conn.execute(text(f"UPDATE {table} SET created_at = :t WHERE analysis_run_id = :run"), {"t": detected, "run": run_id})
        conn.execute(
            text(
                "UPDATE ops_operational_cases SET created_at = :created, updated_at = :resolved, "
                "resolved_at = :resolved WHERE id = :case"
            ),
            {"created": detected + timedelta(minutes=2), "resolved": resolved, "case": case_id},
        )
        conn.execute(
            text("UPDATE analyzer_learning_outcomes SET created_at = :t, resolved_at = :t WHERE case_id = :case"),
            {"t": resolved, "case": case_id},
        )
    engine.dispose()
    # Re-index so the memory entry carries the backdated timestamps too.
    send("POST", f"/api/cases/{case_id}/memory/index", {})
    log(f"past incident dated {detected.date()} ({scenario.PAST_INCIDENT_DAYS_AGO} days ago) and indexed into operational memory")


def main() -> int:
    marker = STATE_DIR / SEEDED_FILE
    if marker.exists():
        log("already seeded, nothing to do")
        return 0

    timeline = scenario.read_timeline(STATE_DIR)
    if timeline is None:
        raise RuntimeError(f"no demo timeline in {STATE_DIR} - demo-history must run first")
    anchor = scenario.parse_time(timeline["anchor"])
    past_times = scenario.past_incident_times(anchor)

    log(f"waiting for the backend at {BACKEND} (first start loads the embedding model)...")
    wait_for_backend()

    seed_change_events(timeline, past_times)
    past = seed_past_incident(anchor)
    backdate_past_incident(past, past_times)

    marker.write_text(
        json.dumps({**past, "seeded_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )
    log("done. The CheckoutApiLatencyHigh alert fires next and is enriched within about a minute.")
    log(f"  Ops Signals UI:   {WEB_URL}")
    log(f"  Slack messages:   {SLACK_SINK_URL}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"FAILED: {exc}")
        raise SystemExit(1)
