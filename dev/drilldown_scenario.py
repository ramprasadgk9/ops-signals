"""Backfill per-pod history into the local Prometheus so finding drill-down can be tried from the UI.

Four services, each telling one of the drill-down stories (docs/finding-drilldown.md), with the
change CHANGE_HOURS_AGO hours ago:

  drill-checkout  http_errors_total        6 pods, pod checkout-7f9-x2 starts failing  -> concentrated
  drill-cart      http_errors_total        4 pods, then 2 new pods arrive and fail      -> new pods
  drill-payments  request_latency_seconds  6 pods, every pod gets slower                -> widespread
  drill-search    request_latency_seconds  6 pods, only search-5d1-s3 gets slower       -> concentrated

The services get their own names: the autonomous planner picks one metric per service and concept,
so a scenario metric on a service that already has, say, an error_rate would be screened out.

Errors are counters (the planner queries `sum by (service) (rate(...))`, so the breakdown shows
shares of the increase); latency is a gauge (`avg by (service) (...)`, so it shows which pods moved).

    python dev/drilldown_scenario.py            # backfill into the docker-compose Prometheus (:9090)
    python dev/drilldown_scenario.py --dry-run  # only write the OpenMetrics file
    python dev/drilldown_scenario.py --deploys  # only record the deploys (backend must be running)

The cart story's new pods come from a deploy: after a backfill (or with --deploys, for history
loaded earlier) the script records deploy DEPLOY_VERSION for cart a minute before those pods first
reported, read from Prometheus. The finding then shows "These 2 new pods started with deploy ...".

Then start the app with OPS_SIGNALS_DRILLDOWN_ENABLED=true and run Autonomous Analysis with the
availability and performance categories, a 24h window and a 10m interval.

History is written once, ending now. Running the script again later would add a second copy of
every series at different times, so it refuses when the scenario is already in Prometheus.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

JOB = "drilldown-scenario"
ENV = "local"
STEP_SECONDS = 30
HISTORY_HOURS = 24
CHANGE_HOURS_AGO = 4
# The cart story's new pods are started by this deploy, recorded this long before they first report.
DEPLOY_POD_PREFIX = "cart-8c2-"
DEPLOY_VERSION = "v1.4.2"
DEPLOY_LEAD_SECONDS = 60
EVENT_SOURCE = "drilldown_scenario.py"


def _rng(*key: object) -> random.Random:
    return random.Random(":".join(str(part) for part in key))


# (service, metric, kind, {pod: (level before, level after)}); None = pod not running then.
# Levels are errors/s for counters and seconds for latency.
SCENARIOS: list[tuple[str, str, str, dict[str, tuple[float | None, float | None]]]] = [
    (
        "drill-checkout",
        "http_errors_total",
        "counter",
        {
            "checkout-7f9-a1": (0.20, 0.21),
            "checkout-7f9-x2": (0.18, 3.60),
            "checkout-7f9-k4": (0.25, 0.26),
            "checkout-7f9-m8": (0.15, 0.16),
            "checkout-7f9-p3": (0.22, 0.22),
            "checkout-7f9-z6": (0.19, 0.20),
        },
    ),
    (
        "drill-cart",
        "http_errors_total",
        "counter",
        {
            "cart-6b4-a1": (0.10, 0.10),
            "cart-6b4-b2": (0.12, 0.12),
            "cart-6b4-c3": (0.09, 0.10),
            "cart-6b4-d4": (0.11, 0.11),
            "cart-8c2-q1": (None, 1.40),
            "cart-8c2-w7": (None, 1.30),
        },
    ),
    (
        "drill-payments",
        "request_latency_seconds",
        "gauge",
        {f"payments-4a9-{name}": (level, level * 2.5) for name, level in
         [("a1", 0.10), ("b2", 0.14), ("c3", 0.12), ("d4", 0.09), ("e5", 0.13), ("f6", 0.11)]},
    ),
    (
        "drill-search",
        "request_latency_seconds",
        "gauge",
        {
            "search-5d1-s1": (0.08, 0.08),
            "search-5d1-s2": (0.09, 0.09),
            "search-5d1-s3": (0.08, 0.36),
            "search-5d1-s4": (0.10, 0.10),
            "search-5d1-s5": (0.07, 0.07),
            "search-5d1-s6": (0.09, 0.09),
        },
    ),
]


def build_openmetrics(end: int) -> str:
    start = end - HISTORY_HOURS * 3600
    change = end - CHANGE_HOURS_AGO * 3600
    families: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    for service, metric, kind, pods in SCENARIOS:
        family = metric.removesuffix("_total") if kind == "counter" else metric
        kinds[family] = kind
        lines = families.setdefault(family, [])
        for pod, (before, after) in pods.items():
            labels = f'job="{JOB}",service="{service}",env="{ENV}",pod="{pod}"'
            total = 0.0
            for t in range(start, end + 1, STEP_SECONDS):
                level = before if t < change else after
                if level is None:
                    continue
                noise = _rng(service, pod, t).gauss(0.0, 0.08)
                if kind == "counter":
                    total += max(0.0, level * (1.0 + noise)) * STEP_SECONDS
                    lines.append(f"{metric}{{{labels}}} {total:.3f} {t}")
                else:
                    lines.append(f"{metric}{{{labels}}} {max(0.001, level * (1.0 + noise)):.5f} {t}")
    out: list[str] = []
    for family, lines in families.items():
        out.append(f"# TYPE {family} {kinds[family]}")
        out.extend(lines)
    out.append("# EOF")
    return "\n".join(out) + "\n"


def already_loaded(prometheus_url: str) -> bool:
    services = "|".join(service for service, *_ in SCENARIOS)
    selector = f'{{job="{JOB}",service=~"{services}"}}'
    query = urlencode({"query": f"count(count_over_time({{__name__=~\"http_errors_total|request_latency_seconds\",{selector[1:]}[{HISTORY_HOURS * 2}h]))"})
    try:
        with urlopen(f"{prometheus_url}/api/v1/query?{query}", timeout=10) as response:
            payload = json.load(response)
    except OSError as exc:
        sys.exit(f"Could not reach Prometheus at {prometheus_url}: {exc}. Is the stack running (scripts/run_all.sh)?")
    return bool(payload.get("data", {}).get("result"))


def backfill(path: Path, *, volume: str, container: str, image: str) -> None:
    subprocess.run(
        [
            "docker", "run", "--rm", "--entrypoint", "promtool",
            "-v", f"{volume}:/prometheus",
            "-v", f"{path.parent}:/data:ro",
            image, "tsdb", "create-blocks-from", "openmetrics", f"/data/{path.name}", "/prometheus",
        ],
        check=True,
    )
    # Prometheus loads new blocks at startup.
    subprocess.run(["docker", "restart", container], check=True, stdout=subprocess.DEVNULL)


def _prometheus_query(prometheus_url: str, query: str) -> list[dict]:
    with urlopen(f"{prometheus_url}/api/v1/query?{urlencode({'query': query})}", timeout=30) as response:
        return json.load(response).get("data", {}).get("result", [])


def find_new_pod_deploys(prometheus_url: str) -> list[dict]:
    """One deploy per (service, env) whose pods match DEPLOY_POD_PREFIX, timed a minute before the
    first of those pods reported. Works for history loaded by any earlier version of this script."""
    selector = f'{{__name__="http_errors_total",pod=~"{DEPLOY_POD_PREFIX}.+"}}'
    lookback = f"{HISTORY_HOURS + 6}h"
    rows = _prometheus_query(prometheus_url, f"min by (service, env) (min_over_time(timestamp({selector})[{lookback}:{STEP_SECONDS}s]))")
    deploys = []
    for row in rows:
        labels = row.get("metric", {})
        if not labels.get("service"):
            continue
        first_seen = float(row["value"][1])
        deploys.append(
            {
                "service": labels["service"],
                "env": labels.get("env"),
                "type": "deploy",
                "version": DEPLOY_VERSION,
                "timestamp": datetime.fromtimestamp(first_seen - DEPLOY_LEAD_SECONDS, tz=timezone.utc).isoformat(),
                "author": "drilldown-scenario",
                "source": EVENT_SOURCE,
                "description": f"Rollout that starts the {DEPLOY_POD_PREFIX}* pods",
            }
        )
    return deploys


def _backend_request(method: str, url: str, token: str | None, payload: object | None = None) -> object:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=10) as response:
        return json.load(response)


def _wait_for_prometheus(prometheus_url: str, seconds: int = 60) -> None:
    # It was just restarted to load the new blocks.
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urlopen(f"{prometheus_url}/-/ready", timeout=5):
                return
        except OSError:
            time.sleep(2)


def record_deploys(prometheus_url: str, backend_url: str, token: str | None) -> int:
    """Record the scenario's deploys once. Never fails the backfill: on any problem, say what to do."""
    try:
        deploys = find_new_pod_deploys(prometheus_url)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Could not read the new pods' start time from Prometheus ({exc}); no deploy recorded.")
        return 1
    if not deploys:
        print(f"No {DEPLOY_POD_PREFIX}* pods in Prometheus yet, so there is no deploy to record. Backfill first.")
        return 1

    status = 0
    for deploy in deploys:
        what = f"deploy {deploy['version']} for {deploy['service']} at {deploy['timestamp']}"
        try:
            existing = _backend_request("GET", f"{backend_url}/api/events?{urlencode({'service': deploy['service'], 'type': 'deploy', 'limit': 500})}", token)
            if any(event.get("source") == EVENT_SOURCE and event.get("version") == deploy["version"] for event in existing):
                print(f"Already recorded: {what}")
                continue
            _backend_request("POST", f"{backend_url}/api/events", token, deploy)
            print(f"Recorded {what}")
        except HTTPError as exc:
            hint = " Set OPS_SIGNALS_EVENTS_TOKEN (or pass --events-token)." if exc.code == 401 else ""
            print(f"The backend refused {what}: HTTP {exc.code}.{hint}")
            status = 1
        except (URLError, OSError, ValueError) as exc:
            print(f"Could not reach Ops Signals at {backend_url} ({exc}). Start it, then run: python dev/drilldown_scenario.py --deploys")
            return 1
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill per-pod drill-down scenarios into the local Prometheus")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--volume", default="ops-signals_prometheus_data", help="docker volume holding Prometheus' data")
    parser.add_argument("--container", default="ops-signals-prometheus")
    parser.add_argument("--image", default="prom/prometheus:v2.54.1")
    parser.add_argument("--dry-run", action="store_true", help="write the OpenMetrics file and stop")
    parser.add_argument("--force", action="store_true", help="backfill even if the scenario is already in Prometheus")
    parser.add_argument("--deploys", action="store_true", help="only record the deploys for history already in Prometheus")
    parser.add_argument("--backend-url", default=f"http://localhost:{os.getenv('BACKEND_PORT', '8001')}")
    parser.add_argument("--events-token", default=os.getenv("OPS_SIGNALS_EVENTS_TOKEN") or os.getenv("OPS_SIGNALS_API_TOKEN"))
    args = parser.parse_args()
    backend_url = args.backend_url.rstrip("/")

    if args.deploys:
        return record_deploys(args.prometheus_url, backend_url, args.events_token)

    end = int(time.time()) - 60
    text = build_openmetrics(end)
    directory = Path(tempfile.mkdtemp(prefix="drilldown-scenario-"))
    path = directory / "history.om"
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {text.count(chr(10)):,} lines to {path}")
    if args.dry_run:
        return 0

    if not args.force and already_loaded(args.prometheus_url):
        print(
            "The drill-down scenario is already in Prometheus; backfilling again would add a second copy.\n"
            "To start over, reset the local Prometheus data:\n"
            f"  docker compose rm -sf prometheus && docker volume rm {args.volume} && docker compose up -d prometheus\n"
            "or pass --force."
        )
        return 1

    directory.chmod(0o755)
    path.chmod(0o644)
    backfill(path, volume=args.volume, container=args.container, image=args.image)
    print(f"Backfilled {HISTORY_HOURS}h of history (change {CHANGE_HOURS_AGO}h ago) and restarted {args.container}.")
    _wait_for_prometheus(args.prometheus_url)
    record_deploys(args.prometheus_url, backend_url, args.events_token)
    print("Next: OPS_SIGNALS_DRILLDOWN_ENABLED=true, then Autonomous Analysis -> availability + performance, 24h window, 10m interval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
