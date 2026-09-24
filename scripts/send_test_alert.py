#!/usr/bin/env python3
"""Fire (or resolve) a test alert through a real Alertmanager, so it reaches the Ops Signals
alert receiver exactly like a production alert would - the fastest way to see an enriched
alert message land in Slack.

Easiest setup: in .env set OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true and a Slack webhook
(OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL or OPS_SIGNALS_SLACK_WEBHOOK_URL), then run
./scripts/run_all.sh - it starts Alertmanager, the demo rules, and the backend on :8001.

Usage:
    ./scripts/send_test_alert.py                       # latency alert on mixed-lab (analyzed)
    ./scripts/send_test_alert.py --scenario status     # up==0 style alert (analysis skipped)
    ./scripts/send_test_alert.py --scenario log        # LogQL alert (analysis skipped)
    ./scripts/send_test_alert.py --scenario no-query   # no rule expression (analysis skipped)

    # also record a deploy for the service first, so "What changed" has something to show
    ./scripts/send_test_alert.py --deploy-minutes-ago 5
    ./scripts/send_test_alert.py --deploy-at 2026-09-23T14:02:00Z

    # resolve a previous test alert (the run id is printed when firing)
    ./scripts/send_test_alert.py --resolve --run-id 20260923-141300

Each run gets a fresh `ops_signals_test_run` label, so Ops Signals treats it as a new alert
rather than a repeat notification of the last one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROMETHEUS_UI = "http://localhost:9090"

SCENARIOS: dict[str, dict] = {
    "latency": {
        "alertname": "TestMixedLabLatencyHigh",
        "labels": {
            "service": "mixed-lab",
            "severity": "warning",
            "job": "ops-signals-mock",
            "instance": "mock-metrics:9101",
            "exported_instance": "mixed-lab-01",
            "env": "local",
        },
        "summary": "mixed-lab p95 latency above 300ms (test alert)",
        "expr": 'request_latency_p95{service="mixed-lab"} > 300',
    },
    "status": {
        "alertname": "TestMockTargetDown",
        "labels": {"job": "ops-signals-mock", "severity": "critical", "instance": "mock-metrics:9101"},
        "summary": "mock metrics target is down (test alert)",
        "expr": 'up{job="ops-signals-mock"} == 0',
    },
    "log": {
        "alertname": "TestCheckoutErrorLogs",
        "labels": {"service": "checkout", "severity": "warning"},
        "summary": "checkout is logging errors (test alert)",
        "expr": 'sum(count_over_time({app="checkout"} |= "error" [5m])) > 10',
    },
    "no-query": {
        "alertname": "TestExternalCheckFailed",
        "labels": {"service": "checkout", "severity": "warning"},
        "summary": "synthetic check failed (test alert, no rule expression)",
        "expr": None,
    },
}


def _post(url: str, payload: object, token: str | None = None) -> int:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urlopen(request, timeout=10) as response:
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="latency")
    parser.add_argument("--alertmanager-url", default="http://localhost:9093")
    parser.add_argument(
        "--ops-signals-url",
        default=f"http://localhost:{os.getenv('BACKEND_PORT', '8001')}",
        help="Backend URL (default: localhost:$BACKEND_PORT, else run_all.sh's 8001)",
    )
    parser.add_argument("--events-token", default=None, help="Bearer token if OPS_SIGNALS_EVENTS_TOKEN is set")
    parser.add_argument("--run-id", default=None, help="Reuse a run id (needed with --resolve)")
    parser.add_argument("--resolve", action="store_true", help="Resolve the alert with this --run-id")
    parser.add_argument("--deploy-minutes-ago", type=float, default=None, help="Record a deploy N minutes ago first")
    parser.add_argument("--deploy-at", default=None, help="Record a deploy at this ISO time first")
    parser.add_argument("--version", default="v1.2.3-test", help="Version string for the deploy event")
    args = parser.parse_args()

    if args.resolve and not args.run_id:
        parser.error("--resolve needs the --run-id printed when the alert was fired")

    scenario = SCENARIOS[args.scenario]
    now = datetime.now(timezone.utc)
    run_id = args.run_id or now.strftime("%Y%m%d-%H%M%S")
    service = scenario["labels"].get("service") or scenario["labels"].get("job")

    if args.deploy_minutes_ago is not None or args.deploy_at:
        deployed_at = (
            datetime.fromisoformat(args.deploy_at.replace("Z", "+00:00"))
            if args.deploy_at
            else now - timedelta(minutes=args.deploy_minutes_ago)
        )
        event = {
            "service": service,
            "type": "deploy",
            "version": args.version,
            "timestamp": deployed_at.isoformat(),
            "author": "send_test_alert",
            "source": "send_test_alert.py",
            "url": "https://example.com/deploys/" + run_id,
        }
        try:
            _post(f"{args.ops_signals_url}/api/events", event, args.events_token)
        except (HTTPError, URLError) as exc:
            sys.exit(f"Could not record the deploy event at {args.ops_signals_url}: {exc}")
        print(f"Recorded deploy {args.version} for {service} at {deployed_at:%H:%M:%S} UTC")

    alert: dict = {
        "labels": {"alertname": scenario["alertname"], "ops_signals_test_run": run_id, **scenario["labels"]},
        "annotations": {"summary": scenario["summary"]},
        "startsAt": now.isoformat(),
    }
    if scenario["expr"]:
        alert["generatorURL"] = f"{PROMETHEUS_UI}/graph?g0.expr={quote(scenario['expr'])}&g0.tab=1"
    if args.resolve:
        # Same labels + an endsAt in the past = resolved; Alertmanager sends it on the next group_interval.
        alert["startsAt"] = (now - timedelta(minutes=1)).isoformat()
        alert["endsAt"] = now.isoformat()

    try:
        _post(f"{args.alertmanager_url}/api/v2/alerts", [alert])
    except (HTTPError, URLError) as exc:
        sys.exit(
            f"Could not reach Alertmanager at {args.alertmanager_url}: {exc}\n"
            "Start it with: docker compose -f docker-compose.yml -f docker-compose.alerting.yml up -d prometheus alertmanager"
        )

    action = "Resolved" if args.resolve else "Fired"
    print(f"{action} {scenario['alertname']} ({args.scenario}) - run id {run_id}")
    if args.resolve:
        print("Alertmanager sends resolutions on its next group_interval (up to ~1 min).")
    else:
        print("Alertmanager forwards it after group_wait (~10s); the Slack message follows once analysis finishes.")
        print(f"Resolve it later with: ./scripts/send_test_alert.py --scenario {args.scenario} --resolve --run-id {run_id}")


if __name__ == "__main__":
    main()
