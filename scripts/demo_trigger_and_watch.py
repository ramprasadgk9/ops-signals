#!/usr/bin/env python3
"""Reset the five-minute demo and narrate it live: deploy -> latency shift -> alert -> enrichment.

Built for presenting: run this one script on stage instead of silently `up`-ing the compose file,
and it prints each stage as it happens so you can talk over it, ending with exactly what to click
open in Slack and in the Findings UI to "identify" the result.

    ./scripts/demo_trigger_and_watch.py

It resets the demo stack (`down -v`, then `up -d`), so the previous run's incident is gone and a
fresh one is seeded. The underlying story is docs/demo.md's: checkout-api deploy v2.14.0, latency
step-up 3 minutes later, alert fires, Ops Signals enriches it. Nothing here is scripted beyond the
reset+wait - the alert travels the real Alertmanager -> Ops Signals path, same as scripts/demo_smoke_test.py
checks in CI.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

COMPOSE_FILE = "docker-compose.demo.yml"


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def fetch_json(url: str):
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read())


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
    return after.split(end, 1)[0].strip()


def wait_for(label: str, check, timeout_seconds: int, poll_seconds: int = 5):
    print(f"... waiting for {label}", flush=True)
    deadline = time.monotonic() + timeout_seconds
    last_error = "not ready yet"
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                print(f"OK   {label}")
                return result
        except (URLError, OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(poll_seconds)
    raise SystemExit(f"FAIL: {label} did not happen within {timeout_seconds}s ({last_error})")


def find_firing_alert(alertmanager_url: str, alert_name: str) -> dict | None:
    for alert in fetch_json(f"{alertmanager_url}/api/v2/alerts"):
        if alert.get("labels", {}).get("alertname") == alert_name and alert.get("status", {}).get("state") == "active":
            return alert
    return None


def find_slack_message(slack_url: str, needle: str) -> str | None:
    for entry in fetch_json(f"{slack_url}/api/messages"):
        text = message_text(entry.get("payload") or {})
        if needle in text:
            return text
    return None


def find_finding(web_url: str, service: str) -> dict | None:
    findings = fetch_json(f"{web_url}/api/findings?service={service}")
    return findings[0] if findings else None


def past_case_seeded(web_url: str) -> dict | None:
    case = fetch_json(f"{web_url}/api/cases/1")
    if case.get("outcome_status") == "resolved" and case.get("memory_status") == "indexed":
        return case
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--web-url", default="http://localhost:8080")
    parser.add_argument("--prometheus-url", default="http://localhost:9091")
    parser.add_argument("--alertmanager-url", default="http://localhost:9094")
    parser.add_argument("--slack-url", default="http://localhost:8090")
    parser.add_argument("--service", default="checkout-api")
    parser.add_argument("--alert-name", default="CheckoutApiLatencyHigh")
    parser.add_argument("--skip-reset", action="store_true", help="reuse an already-running demo instead of down -v / up -d")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for each stage")
    args = parser.parse_args()

    if not args.skip_reset:
        print("\n=== resetting the demo stack (fresh incident) ===")
        run(["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"])
        run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d"])

    print("\n=== 1. deploy + latency shift (seeded into history and the live series) ===")
    wait_for(
        "the backend to come up",
        lambda: fetch_json(f"{args.web_url}/api/health"),
        timeout_seconds=min(args.timeout, 120),
        poll_seconds=3,
    )
    wait_for(
        "the seeder to record deploys and the past incident",
        lambda: past_case_seeded(args.web_url),
        timeout_seconds=min(args.timeout, 180),
        poll_seconds=5,
    )
    print("    deploy v2.14.0 landed, latency stepped up ~45 min of backfilled history ago")
    print(f"    Prometheus is scraping the live series: {args.prometheus_url}/graph")

    print("\n=== 2. Prometheus alert fires ===")
    wait_for(
        f"{args.alert_name} to go active in Alertmanager",
        lambda: find_firing_alert(args.alertmanager_url, args.alert_name),
        timeout_seconds=args.timeout,
    )
    print(f"    see it at: {args.alertmanager_url}/#/alerts")

    print("\n=== 3. Ops Signals enriches the alert in Slack ===")
    text = wait_for(
        "the enriched message in the Slack sink",
        lambda: find_slack_message(args.slack_url, f"[FIRING] {args.alert_name}"),
        timeout_seconds=args.timeout,
    )
    print(f"    open it at: {args.slack_url}")
    print("\n    --- What happened ---")
    print("    " + section(text, "What happened", "What changed").replace("\n", "\n    "))
    print("\n    --- What changed ---")
    print("    " + section(text, "What changed", "Seen before").replace("\n", "\n    "))
    print("\n    --- Seen before ---")
    after_seen_before = text.split("Seen before", 1)[1] if "Seen before" in text else ""
    print("    " + after_seen_before.strip().replace("\n", "\n    "))

    print("\n=== 4. the same result in the Findings UI ===")
    finding = wait_for(
        f"a finding for {args.service} to appear via the API",
        lambda: find_finding(args.web_url, args.service),
        timeout_seconds=args.timeout,
    )
    print(f"    finding id={finding['id']}  importance={finding.get('importance_score')}")
    print(f"    title: {finding.get('title')}")
    print(f"    open the UI at: {args.web_url}  ->  Findings  ->  the top card for {args.service}")

    print("\n=== ready to present ===")
    print(f"  Slack:      {args.slack_url}")
    print(f"  Findings:   {args.web_url}")
    print(f"  Prometheus: {args.prometheus_url}")
    print(f"  Alertmanager: {args.alertmanager_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
