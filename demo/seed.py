"""One-shot: seed the demo story's history through the public API, then exit
(docker-compose.demo.yml: demo-seeder). Alertmanager only starts after this succeeds, so the alert
always lands on a fully seeded backend. The story itself is in demo/scenario.py.

1. CI deploy events: checkout-api (today, yesterday, five weeks ago) and orders (today).
   search-svc's deploy is left for deploy discovery to find.
2. Past problems: analyze a CSV of each, open a case from its finding, record the root cause and
   fix (and the checkout write-up), and index the cases into operational memory.
3. "Was this real?" answers on past payments-db and search-svc findings.
4. Move the past problems back to when they happened. The API stamps everything "now".
5. A scheduled analysis every 5 minutes over the demo Prometheus, and one run right away.
6. Once the OTLP analysis reports the orders problem, a case on it, left in progress.

Today's problems come from the real paths: live metrics, the scheduled analysis, OTLP ingestion,
deploy discovery, and the alert (a Prometheus rule fires, Alertmanager routes it to
/api/integrations/alertmanager, and the backend enriches it and posts to the Slack sink).

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


def seed_change_events(timeline: dict[str, str], anchor: datetime) -> None:
    ci = {"type": "deploy", "env": scenario.ENV, "source": "github-actions"}
    checkout_past = next(i for i in scenario.PAST_INCIDENTS if i.key == "checkout-rollback").times(anchor)
    events = [
        {
            **ci,
            "service": scenario.SERVICE,
            "timestamp": checkout_past["deploy_at"].isoformat(),
            "version": scenario.PAST_DEPLOY_VERSION,
            "author": "maya",
            "description": "Switch checkout pricing lookups to the new catalog client",
        },
        {
            **ci,
            "service": scenario.SERVICE,
            "timestamp": timeline["previous_deploy_at"],
            "version": scenario.PREVIOUS_DEPLOY_VERSION,
            "author": "dev-bot",
            "description": "Dependency bumps",
        },
        {
            **ci,
            "service": scenario.SERVICE,
            "timestamp": timeline["deploy_at"],
            "version": scenario.CURRENT_DEPLOY_VERSION,
            "author": "alex",
            "description": "Enable per-item tax calculation in checkout",
        },
        {
            **ci,
            "service": scenario.ORDERS_SERVICE,
            "timestamp": timeline["orders_deploy_at"],
            "version": scenario.ORDERS_DEPLOY_VERSION,
            "author": "sam",
            "description": "Switch address validation to the new provider client",
        },
        # search-svc's deploy is not sent: Ops Signals finds it on search_build_info by itself.
    ]
    # A seeder run that failed halfway may already have recorded some of these.
    existing = {
        (event.get("service"), event.get("version"))
        for service in {event["service"] for event in events}
        for event in get(f"/api/events?service={service}&limit=500")
    }
    events = [event for event in events if (event["service"], event["version"]) not in existing]
    if events:
        send("POST", "/api/events", events)
    log(f"recorded {len(events)} CI deploy events (checkout-api {scenario.CURRENT_DEPLOY_VERSION} at {timeline['deploy_at']})")


def significant_findings(run_id: str) -> list[dict]:
    # The API returns them by importance, highest first.
    return [f for f in get(f"/api/findings?analysis_run_id={run_id}") if f.get("health_status") != "normal"]


def seed_past_incident(incident: scenario.PastIncident, anchor: datetime) -> dict[str, object]:
    run = post_csv(
        "/api/ingestion/csv-run",
        f"{incident.key}.csv",
        incident.csv(anchor),
        {"provider": "generic", "service": incident.service, "metric_name": incident.metric, "interval": "30s"},
    )
    run_id = run["analysis_run_id"]
    findings = significant_findings(run_id)
    if not findings:
        raise RuntimeError(f"past problem {incident.key} (run {run_id}) produced no significant finding")
    seeded: dict[str, object] = {"key": incident.key, "analysis_run_id": run_id, "finding_ids": [f["id"] for f in findings]}
    log(f"{incident.key}: {incident.days_ago:g} days ago, {len(findings)} finding(s), top {findings[0]['title']!r}")
    if not incident.case:
        return seeded

    case_id = send("POST", f"/api/cases/findings/{findings[0]['id']}/create", {})["case_id"]
    for step in ("investigation", "rca", "resolution", "writeup"):
        if step in incident.case:
            send("PATCH", f"/api/cases/{case_id}/{step}", incident.case[step])
    seeded["case_id"] = case_id
    log(f"{incident.key}: case #{case_id} resolved: {incident.case['resolution']['corrective_action']}")
    return seeded


def backdate(seeded: list[dict[str, object]], anchor: datetime) -> None:
    """Move each past problem's rows back to when it happened. The API stamps everything "now",
    which would make a three-week-old incident look like it happened a minute ago (and alert
    enrichment would reuse its finding as today's analysis)."""
    from sqlalchemy import create_engine, text

    incidents = {incident.key: incident for incident in scenario.PAST_INCIDENTS}
    url = os.environ.get("OPS_SIGNALS_DATABASE_URL") or os.environ["OPS_INTEL_DATABASE_URL"]
    engine = create_engine(url)
    with engine.begin() as conn:
        for item in seeded:
            times = incidents[str(item["key"])].times(anchor)
            run_id, detected, resolved = item["analysis_run_id"], times["detected_at"], times["resolved_at"]
            conn.execute(text("UPDATE analysis_runs SET created_at = :t WHERE id = :run"), {"t": detected, "run": run_id})
            for table in ("ops_operational_signals", "ops_operational_findings"):
                conn.execute(text(f"UPDATE {table} SET created_at = :t WHERE analysis_run_id = :run"), {"t": detected, "run": run_id})
            # Patterns matched in the past run, so Behavior Intelligence doesn't list them as active now.
            conn.execute(
                text("UPDATE ops_behavior_findings SET created_at = :t, last_seen_at = :t WHERE analysis_run_id = :run"),
                {"t": detected, "run": run_id},
            )
            conn.execute(
                text("UPDATE ops_finding_feedback SET created_at = :t, updated_at = :t WHERE finding_id = ANY(:ids)"),
                {"t": detected + timedelta(hours=2), "ids": list(item["finding_ids"])},
            )
            case_id = item.get("case_id")
            if case_id is None:
                continue
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
    # Re-index so the memory entries carry the backdated timestamps too.
    for item in seeded:
        if item.get("case_id") is not None:
            send("POST", f"/api/cases/{item['case_id']}/memory/index", {})
    log("past problems moved back to when they happened and indexed into operational memory")


def seed_feedback(seeded: list[dict[str, object]]) -> None:
    """The team's answers to "Was this real?" on past findings: five on payments-db (enough for its
    own rate), two on search-svc (it shows "2 of 5 answers")."""
    wanted = {"payments": 5, "search": 2}
    answered = {key: 0 for key in wanted}
    for item in seeded:
        group = str(item["key"]).split("-", 1)[0]
        for finding_id in item["finding_ids"]:
            if group in wanted and answered[group] < wanted[group]:
                send("POST", f"/api/findings/{finding_id}/feedback", {"verdict": "real_problem"})
                answered[group] += 1
    log(f"recorded 'Was this real?' answers: {answered}")


def scheduled_analysis_request() -> dict[str, object]:
    return {
        "name": "Demo shop, every 5 minutes",
        "connection_id": "default",
        "scope": {"environment": scenario.ENV, "all_services": True, "max_series_per_metric": 20},
        "monitoring_selection": {
            "categories": ["performance", "capacity", "availability", "reliability", "custom"],
            "custom_constraints": {
                "explicit_metrics": [scenario.BACKLOG_METRIC, scenario.DB_WAIT_METRIC, scenario.DB_ACTIVE_METRIC]
            },
        },
        "execution": {"interval": "1m", "analysis_window": "6h", "max_metrics_per_run": 100},
    }


def start_scheduled_analysis() -> None:
    """A scheduled analysis every 5 minutes over the demo Prometheus, plus one run now so the
    findings are there when the first visitor opens the UI."""
    request = scheduled_analysis_request()
    if not any(policy.get("name") == request["name"] for policy in get("/api/autonomous/policies")):
        policy = send("POST", "/api/autonomous/policies", {**request, "schedule_minutes": 5})
        send("PATCH", f"/api/autonomous/policies/{policy['id']}/status", {"enabled": True})
    result = send("POST", "/api/autonomous/run-once", request)
    log(f"scheduled analysis every 5 minutes; first run: {json.dumps(result.get('summary') or {}, default=str)[:300]}")


def seed_orders_case(timeout_seconds: int = 420) -> int | None:
    """Wait for the OTLP analysis to report the orders problem, then open a case on it and leave it
    in progress. Skipped (not failed) if the finding doesn't show up in time."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        findings = [
            f for f in get(f"/api/findings?service={scenario.ORDERS_SERVICE}&limit=50")
            if f.get("health_status") != "normal" and scenario.ORDERS_FAILED_METRIC in (f.get("metric_name") or "")
        ]
        if findings:
            case_id = send("POST", f"/api/cases/findings/{findings[0]['id']}/create", {})["case_id"]
            for step, body in scenario.orders_case_notes().items():
                send("PATCH", f"/api/cases/{case_id}/{step}", body)
            log(f"orders: case #{case_id} opened on {findings[0]['title']!r}, left in progress")
            return case_id
        time.sleep(10)
    log(f"orders: no OTLP finding after {timeout_seconds}s; skipping the in-progress case")
    return None


def main() -> int:
    marker = STATE_DIR / SEEDED_FILE
    if marker.exists():
        log("already seeded, nothing to do")
        return 0

    timeline = scenario.read_timeline(STATE_DIR)
    if timeline is None:
        raise RuntimeError(f"no demo timeline in {STATE_DIR} - demo-history must run first")
    anchor = scenario.parse_time(timeline["anchor"])

    log(f"waiting for the backend at {BACKEND} (first start loads the embedding model)...")
    wait_for_backend()

    seed_change_events(timeline, anchor)
    seeded = [seed_past_incident(incident, anchor) for incident in scenario.PAST_INCIDENTS]
    seed_feedback(seeded)
    backdate(seeded, anchor)
    start_scheduled_analysis()
    orders_case = seed_orders_case()

    marker.write_text(
        json.dumps(
            {"past": seeded, "orders_case_id": orders_case, "seeded_at": datetime.now(timezone.utc).isoformat()},
            indent=2,
        )
        + "\n",
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
