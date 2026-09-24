#!/usr/bin/env python3
"""Check that the five-minute demo (docker-compose.demo.yml) tells its whole story.

Waits for the enriched alert to reach the Slack sink, then checks every part of it: the analysis
found the shift, the deploy was correlated, and the past case was matched. Exits non-zero naming
whatever is missing. Used by CI (.github/workflows/demo-smoke.yml) and handy locally:

    docker compose -f docker-compose.demo.yml up -d
    ./scripts/demo_smoke_test.py

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


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
    args = parser.parse_args()

    print(f"waiting up to {args.timeout}s for the enriched alert at {args.slack_url} ...", flush=True)
    text = wait_for_alert_message(args.slack_url.rstrip("/"), args.timeout)

    checks = [
        ("analysis found the latency shift", "baseline shift" in text and "Not analyzed" not in text),
        ("change start time reported", "Change started around" in text),
        ("deploy v2.14.0 correlated", "deploy `v2.14.0`" in text),
        ("verdict from past outcomes", "Verdict: *likely real*" in text),
        ("similar past case matched", "Most similar case:" in text),
        ("past fix surfaced", "Rolled back v2.9.0" in text),
    ]

    try:
        case = fetch_json(f"{args.web_url.rstrip('/')}/api/cases/1")
        checks.append(("past case resolved and indexed (via the web UI's /api proxy)",
                       case.get("outcome_status") == "resolved" and case.get("memory_status") == "indexed"))
    except (URLError, OSError, ValueError) as exc:
        checks.append((f"web UI /api proxy reachable ({exc})", False))

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
