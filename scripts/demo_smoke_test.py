#!/usr/bin/env python3
"""Check that the five-minute demo (docker-compose.demo.yml) tells its whole story.

Waits for the enriched alert to reach the Slack sink and checks every part of it (the analysis
found the shift, the deploy was correlated, the past case was matched), then checks the rest of the
story through the API: the pods each change came from, both combined patterns from the scheduled
analysis, the fix that didn't stick, the recurring problem, the deploy found automatically, the
OTLP service with its case and custom settings, and the published write-up (demo/scenario.py).
Exits non-zero naming whatever is missing. Used by CI (.github/workflows/demo-smoke.yml) and handy
locally:

    docker compose -f docker-compose.demo.yml up -d
    ./scripts/demo_smoke_test.py

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


def fetch_json(url: str, body: object | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _recent(stamp: str | None, minutes: int = 120) -> bool:
    """Made by today's live analysis, not part of the seeded (backdated) history."""
    if not stamp:
        return False
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return when > datetime.now(timezone.utc) - timedelta(minutes=minutes)


def story_checks(api: str) -> list[tuple[str, bool]]:
    """The rest of the story, beyond the alert. Each check reads the API the UI reads."""
    findings = fetch_json(f"{api}/findings?limit=200")
    live = [f for f in findings if _recent(f.get("created_at")) and f.get("health_status") != "normal"]
    patterns = [p for p in fetch_json(f"{api}/behavior-evaluations") if _recent(p.get("last_seen_at"))]
    cases = fetch_json(f"{api}/cases?limit=50")

    def pattern(rule: str, service: str) -> bool:
        # From the scheduled analysis: one run per metric, so the match spans at least two runs.
        return any(p["definition_id"] == rule and p.get("service") == service and len(p.get("analysis_run_ids") or []) >= 2 for p in patterns)

    def live_finding(service: str, metric: str) -> dict | None:
        return next((f for f in live if f.get("service") == service and f.get("metric_name") == metric), None)

    pool_case = next((c for c in cases if "pool from 20 to 40" in (c.get("corrective_action") or "")), None)
    wait = live_finding("payments-db", "db_connection_wait_seconds")
    came_back = None
    if wait:
        [seen] = fetch_json(f"{api}/findings/seen-before", {"finding_ids": [wait["id"]]})
        came_back = (seen.get("came_back") or {}).get("case_id")
    recurring = fetch_json(f"{api}/memory/recurring-problems?name=false").get("problems") or []
    events = fetch_json(f"{api}/events?service=search-svc&limit=50")
    processing = live_finding("orders", "orders_processing_seconds")

    def breakdown(service: str, metric: str) -> dict:
        """The pod drill-down on today's finding (the latest one with a breakdown that worked)."""
        for f in live:
            found = (f.get("comparison_json") or {}).get("breakdown") or {}
            if f.get("service") == service and f.get("metric_name") == metric and found.get("status") == "ok":
                return found
        return {}

    checkout_pods = breakdown("checkout-api", "request_latency_p95")
    search_pods = breakdown("search-svc", "error_rate")
    return [
        ("checkout-api change came from the new pods of the rollout",
         checkout_pods.get("new_parts", 0) >= 3 and checkout_pods.get("parts_changed") == checkout_pods.get("new_parts")),
        ("search-svc errors came from 1 of 4 pods",
         search_pods.get("parts_changed") == 1 and search_pods.get("parts_total") == 4),
        ("combined pattern: payments-db pool exhaustion, from the scheduled analysis", pattern("pool_exhaustion", "payments-db")),
        ("combined pattern: search-svc cascading failure, from the scheduled analysis", pattern("latency_error_cascade", "search-svc")),
        ("payments-db problem came back after the 9-day-old fix",
         pool_case is not None and came_back == pool_case["id"]),
        ("payments-db is a recurring problem (3+ times)",
         any("payments-db" in (g.get("services") or []) and (g.get("occurrences") or 0) >= 3 for g in recurring)),
        ("search-svc deploy 1.9.0 found automatically on build_info",
         any(e.get("version") == "1.9.0" and e.get("source") == "ops-signals:build_info" for e in events)),
        ("orders failed-orders problem found from OTLP", live_finding("orders", "orders_failed") is not None),
        ("orders case left in progress", any(c.get("investigation_status") == "in_progress" for c in cases)),
        ("orders processing finding made with the team's custom settings",
         processing is not None and bool(processing.get("custom_settings"))),
        ("checkout-api past case published with a write-up", any(c.get("id") == 1 and c.get("writeup") for c in cases)),
    ]


def message_text(payload: dict) -> str:
    parts = [payload.get("text") or ""]
    for block in payload.get("blocks") or []:
        if block.get("text"):
            parts.append(block["text"].get("text", ""))
        for item in block.get("fields") or []:
            parts.append(item.get("text", ""))
        for item in block.get("elements") or []:
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def section(text: str, start: str, end: str) -> str:
    after = text.split(start, 1)[1] if start in text else ""
    return after.split(end, 1)[0]


def wait_for_alert_message(slack_url: str, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no messages yet"
    while time.monotonic() < deadline:
        try:
            for entry in fetch_json(f"{slack_url}/api/messages"):
                text = message_text(entry.get("payload") or {})
                if "[FIRING] CheckoutApiLatencyHigh" in text:
                    return text
        except (URLError, OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise SystemExit(f"FAIL: no enriched CheckoutApiLatencyHigh message within {timeout_seconds}s ({last_error})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--web-url", default="http://localhost:8080")
    parser.add_argument("--slack-url", default="http://localhost:8090")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for the alert message")
    parser.add_argument("--story-timeout", type=int, default=300, help="seconds to wait for the rest of the story after the alert")
    args = parser.parse_args()

    print(f"waiting up to {args.timeout}s for the enriched alert at {args.slack_url} ...", flush=True)
    text = wait_for_alert_message(args.slack_url.rstrip("/"), args.timeout)

    # Only the "What happened" section: the similar past case further down is also a baseline
    # shift, so a check over the whole message would pass even if today's analysis missed it.
    what_happened = section(text, "What happened", "What changed")
    checks = [
        ("analysis found the latency shift", "baseline shift" in what_happened),
        ("change start time reported", "Change started around" in what_happened),
        ("deploy v2.14.0 correlated", "deploy `v2.14.0`" in text),
        ("verdict from past outcomes", "Verdict: *likely real*" in text),
        ("similar past case matched", "Most similar case:" in text),
        ("past fix surfaced", "Fix: Roll back the deploy" in text),
    ]

    api = f"{args.web_url.rstrip('/')}/api"
    try:
        case = fetch_json(f"{api}/cases/1")
        checks.append(("past case resolved and indexed (via the web UI's /api proxy)",
                       case.get("outcome_status") == "resolved" and case.get("memory_status") == "indexed"))
        # Deploy discovery runs every 2 minutes in the demo; give the rest of the story a few tries.
        deadline = time.monotonic() + args.story_timeout
        story = story_checks(api)
        while not all(ok for _, ok in story) and time.monotonic() < deadline:
            time.sleep(15)
            story = story_checks(api)
        checks += story
    except (URLError, OSError, ValueError) as exc:
        checks.append((f"web UI /api reachable ({exc})", False))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print("\nMessage received:\n" + text, file=sys.stderr)
        return 1
    print("demo smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
