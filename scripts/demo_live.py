#!/usr/bin/env python3
"""Live demo: real alerts through Alertmanager, with pod breakdown and deploy timing.

Run it in a second terminal while ./scripts/run_all.sh runs in the first. It serves a small set
of per-pod metrics that Prometheus scrapes every 5s, changes them on demand (a rollout, a slow
rise, a spike, a staging deploy), records the matching deploy events, and fires each alert
through Alertmanager. The enriched messages appear in a local Slack lookalike
(http://localhost:8095) and are summarized in this terminal.

One-time setup, in .env (then start ./scripts/run_all.sh):

    OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true
    OPS_SIGNALS_DRILLDOWN_ENABLED=true
    OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL=http://localhost:8095/webhook
    OPS_SIGNALS_ALERT_MIN_STEP=5s
    OPS_SIGNALS_ALERT_SCRAPE_INTERVAL=5s

Then:

    ./scripts/demo_live.py

Metrics need a few minutes of history before the first alert; the menu shows when it's ready.
Each scenario runs once per start of the script, since the pods it changes stay changed.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from demo import slack_sink  # noqa: E402  (standard library only)

METRICS_PORT = 9105
SLACK_PORT = 8095
PROMETHEUS_JOB = "ops-signals-live-demo"
WARMUP_SECONDS = 240  # alert analysis needs ~30 points of history at the 5s step
AFTER_CHANGE_SECONDS = 90  # and some points after the change before the alert fires
COMPOSE = "docker compose -f docker-compose.yml -f docker-compose.alerting.yml"


# --- metrics --------------------------------------------------------------------------------------


@dataclass
class Pods:
    """One service's pods. `level(pod, now)` gives each pod's value; changes are set live."""

    metric: str
    service: str
    pods: list[str]
    base: float
    noise: float = 0.02
    ramp_per_second: float = 0.0  # slow rise, from the moment the script started
    extra_pods: dict[str, float] = field(default_factory=dict)  # pod -> level, appear when triggered
    step_to: float | None = None  # every pod moves to this level when triggered
    spike: tuple[str, float, float] | None = None  # (pod, added value, seconds) when triggered
    triggered_at: float | None = None

    def samples(self, started_at: float, now: float) -> list[tuple[str, float]]:
        rng = random.Random(f"{self.service}:{int(now // 5)}")
        rows = []
        ramp = self.ramp_per_second * (now - started_at)
        live = self.triggered_at is not None and now >= self.triggered_at
        for pod in self.pods:
            level = self.step_to if (live and self.step_to is not None) else self.base
            if live and self.spike and pod == self.spike[0] and now - self.triggered_at < self.spike[2]:
                level += self.spike[1]
            rows.append((pod, level + ramp))
        if live:
            rows.extend((pod, level) for pod, level in self.extra_pods.items())
        return [(pod, value * (1 + rng.uniform(-self.noise, self.noise))) for pod, value in rows]


SERVICES = {
    "rollout": Pods("demo_request_latency_ms", "checkout", [f"checkout-{i}" for i in range(1, 5)], base=180.0,
                    extra_pods={"checkout-5": 620.0, "checkout-6": 600.0}),
    "slow_rise": Pods("demo_consumer_lag", "orders-worker", [f"orders-worker-{i}" for i in range(1, 4)], base=400.0,
                      ramp_per_second=1.5),
    "spike": Pods("demo_queue_latency_ms", "payments-worker", [f"payments-worker-{i}" for i in range(1, 5)], base=200.0,
                  ramp_per_second=0.15, spike=("payments-worker-3", 1400.0, 30.0)),
    "staging": Pods("demo_request_latency_ms", "cart", [f"cart-{i}" for i in range(1, 5)], base=150.0, step_to=290.0),
}


class Demo:
    def __init__(self) -> None:
        self.started_at = time.time()
        # Every series carries this run's id and every alert query filters on it, so a restarted
        # script never mixes in the previous run's pods (Prometheus keeps them for the lookback).
        self.run_id = uuid.uuid4().hex[:6]
        # Deploy events stay in the database, so each run uses its own patch number: a restarted
        # demo shouldn't list the last run's "v2.4.0" next to this one's.
        self.patch = int(self.started_at // 60) % 90 + 10
        self.fired: list[dict] = []
        self.done: set[str] = set()

    def version(self, minor: str, suffix: str = "") -> str:
        return f"v{minor}.{self.patch}{suffix}"

    def exposition(self) -> str:
        now = time.time()
        lines, typed = [], set()
        for pods in SERVICES.values():
            if pods.metric not in typed:
                typed.add(pods.metric)
                lines.append(f"# TYPE {pods.metric} gauge")
            for pod, value in pods.samples(self.started_at, now):
                lines.append(f'{pods.metric}{{service="{pods.service}",pod="{pod}",env="prod",demo_run="{self.run_id}"}} {value:.3f}')
        return "\n".join(lines) + "\n"


DEMO = Demo()


class QuietSlackHandler(slack_sink.Handler):
    def log_message(self, *args) -> None:
        return


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = DEMO.exposition().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return


# --- talking to the stack ---------------------------------------------------------------------------


def _request(method: str, url: str, payload: object | None = None, token: str | None = None, timeout: float = 10) -> object:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw and raw[:1] in b"[{" else raw.decode(errors="replace")


@dataclass
class Stack:
    backend: str
    alertmanager: str
    prometheus: str
    token: str | None

    def deploy(self, service: str, version: str, minutes_ago: float, env: str = "prod") -> None:
        at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        _request("POST", f"{self.backend}/api/events", {
            "service": service, "type": "deploy", "version": version, "env": env, "author": "demo",
            "timestamp": at.isoformat(), "source": "demo_live.py",
            "url": f"https://example.com/{service}/releases/{version}",
        }, self.token)
        print(f"  recorded deploy {version} ({env}) for {service} at {at:%H:%M:%S} UTC")

    def fire(self, name: str, service: str, expr: str, summary: str, severity: str = "warning") -> dict:
        alert = {
            "labels": {"alertname": name, "service": service, "env": "prod", "severity": severity,
                       "demo_alert": uuid.uuid4().hex[:8]},
            # 1h is the smallest lookback the analysis takes. With the default 6h, the 2000-point
            # cap would raise the 5s step to 11s and a 30s spike would be 2-3 points.
            "annotations": {"summary": summary, "ops_signals_lookback": "1h"},
            "startsAt": datetime.now(timezone.utc).isoformat(),
            "generatorURL": f"{self.prometheus}/graph?g0.expr={quote(expr)}&g0.tab=1",
        }
        _request("POST", f"{self.alertmanager}/api/v2/alerts", [alert])
        DEMO.fired.append(alert)
        print(f"  fired {name} through Alertmanager")
        return alert

    def resolve_all(self) -> None:
        now = datetime.now(timezone.utc)
        alerts = [{**alert, "startsAt": alert["startsAt"], "endsAt": now.isoformat()} for alert in DEMO.fired]
        if alerts:
            _request("POST", f"{self.alertmanager}/api/v2/alerts", alerts)
        print(f"Resolved {len(alerts)} alert(s); the follow-ups arrive within about a minute.")
        DEMO.fired.clear()

    def target_health(self) -> str | None:
        targets = _request("GET", f"{self.prometheus}/api/v1/targets?state=active")
        for target in targets["data"]["activeTargets"]:
            if target["labels"].get("job") == PROMETHEUS_JOB:
                return target["health"]
        return None


def _message_for(alertname: str, since: float, timeout: float = 360) -> dict | None:
    """Wait for the local Slack lookalike to receive the enriched message for this alert."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with slack_sink._lock:
            messages = list(slack_sink._messages)
        for message in messages:
            text = message.get("payload", {}).get("text", "")
            received = datetime.fromisoformat(message.get("received_at", "1970-01-01T00:00:00+00:00")).timestamp()
            if alertname in text and "[FIRING]" in text and received >= since:
                return message["payload"]
        time.sleep(2)
    return None


def _print_sections(payload: dict) -> None:
    for block in payload.get("blocks", []):
        text = block.get("text", {}).get("text", "") if isinstance(block.get("text"), dict) else ""
        if text.startswith(("*📈", "*🚀")):
            print("  " + text.replace("\n", "\n  "))
            print()


def _wait(seconds: float, label: str) -> None:
    end = time.time() + seconds
    while (left := end - time.time()) > 0:
        print(f"\r  {label}: {int(left):3d}s ", end="", flush=True)
        time.sleep(min(1.0, left))
    print(f"\r  {label}: done      ")


def _warmup() -> None:
    left = WARMUP_SECONDS - (time.time() - DEMO.started_at)
    if left > 0:
        _wait(left, "building metric history first")


# --- scenarios --------------------------------------------------------------------------------------


def _query(agg: str, key: str) -> str:
    pods = SERVICES[key]
    return f'{agg} by (service) ({pods.metric}{{service="{pods.service}",demo_run="{DEMO.run_id}"}})'


def _run(stack: Stack, name: str, service: str, expr: str, summary: str, expect: str) -> None:
    since = time.time()
    stack.fire(name, service, expr, summary)
    print("  waiting for the enriched message (Alertmanager group wait + analysis)...")
    payload = _message_for(name, since)
    if payload is None:
        print(f"  No message after 6 min. Check the backend log, and that .env sends Slack to http://localhost:{SLACK_PORT}/webhook.")
        return
    print()
    _print_sections(payload)
    print(f"  Expected: {expect}")
    print(f"  Full message: http://localhost:{SLACK_PORT}")


def rollout(stack: Stack) -> None:
    version = DEMO.version("2.4")
    print(f"\nRollout: deploy {version} to checkout; two new pods come up slow.")
    _warmup()
    stack.deploy("checkout", version, minutes_ago=1)
    SERVICES["rollout"].triggered_at = time.time()
    _wait(AFTER_CHANGE_SECONDS, "letting the new pods serve traffic")
    _run(stack, "CheckoutLatencyHigh", "checkout",
         _query("avg", "rollout") + " > 250",
         "checkout average latency above 250ms",
         f"a step change that started ~1 min after deploy {version}, and 'Where: 2 of 6 pods' (both new: a rollout).")


def slow_rise(stack: Stack) -> None:
    print("\nSlow rise: orders-worker consumer lag has been creeping up since the demo started.")
    _warmup()
    version = DEMO.version("5.1")
    stack.deploy("orders-worker", version, minutes_ago=2)
    _run(stack, "OrdersConsumerLagHigh", "orders-worker",
         _query("sum", "slow_rise") + " > 1500",
         "orders-worker consumer lag above 1500 messages",
         f"a gradual trend with no clear start time: deploy {version} listed for reference, no 'Started after'.")


def spike(stack: Stack) -> None:
    print("\nSpike on a slow rise: one payments-worker pod spikes right after a deploy.")
    _warmup()
    version = DEMO.version("3.2")
    stack.deploy("payments-worker", version, minutes_ago=1)
    SERVICES["spike"].triggered_at = time.time()
    _wait(AFTER_CHANGE_SECONDS, "spike, then back to normal")
    _run(stack, "PaymentsQueueLatencyHigh", "payments-worker",
         _query("avg", "spike") + " > 400",
         "payments-worker queue latency above 400ms",
         f"'Spike started ~1 min after deploy {version}', noting the slow rise, and 'Where: only pod payments-worker-3'.")


def staging(stack: Stack) -> None:
    print("\nStaging deploy ignored: cart slows down on every pod after a prod deploy; a staging deploy happens too.")
    _warmup()
    prod, staging_version = DEMO.version("6.9"), DEMO.version("7.0", "-rc1")
    stack.deploy("cart", prod, minutes_ago=1.5, env="prod")
    stack.deploy("cart", staging_version, minutes_ago=0.5, env="staging")
    SERVICES["staging"].triggered_at = time.time()
    _wait(AFTER_CHANGE_SECONDS, "letting the slowdown build up")
    _run(stack, "CartLatencyHigh", "cart",
         _query("avg", "staging") + " > 220",
         "cart average latency above 220ms",
         f"'Started after deploy {prod}' only (the staging {staging_version} is skipped), and 'Where: all 4 pods' (not one bad pod).")


SCENARIOS = {
    "1": ("rollout", "Rollout: deploy, then 2 new checkout pods slow down   (step change + new pods)", rollout),
    "2": ("slow_rise", "Slow rise: orders-worker consumer lag creeps up     (trend: no 'started after')", slow_rise),
    "3": ("spike", "Spike on a slow rise: one payments pod spikes       (spike timing + one pod)", spike),
    "4": ("staging", "Staging deploy ignored: cart slows on every pod    (env matching + all pods)", staging),
}


# --- startup and menu ---------------------------------------------------------------------------------


def _serve(port: int, handler: type[BaseHTTPRequestHandler], what: str) -> None:
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    except OSError as exc:
        sys.exit(f"Port {port} for the {what} is in use ({exc}). Stop whatever uses it and try again.")
    threading.Thread(target=server.serve_forever, daemon=True).start()


def _preflight(stack: Stack) -> None:
    problems = []
    try:
        _request("GET", f"{stack.backend}/api/events?limit=1", token=stack.token, timeout=5)
    except (HTTPError, URLError, OSError) as exc:
        problems.append(f"backend not reachable at {stack.backend} ({exc}). Is ./scripts/run_all.sh running?")
    try:
        _request("GET", f"{stack.alertmanager}/-/ready", timeout=5)
    except (HTTPError, URLError, OSError):
        problems.append(f"Alertmanager not reachable at {stack.alertmanager}. Set OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true in .env and restart run_all.sh.")
    try:
        health = stack.target_health()
        if health is None:
            # The scrape job lives in grafana/prometheus/prometheus.alerting.yml; reload picks it up.
            _request("POST", f"{stack.prometheus}/-/reload", timeout=5)
            time.sleep(2)
            health = stack.target_health()
        if health is None:
            problems.append(f"Prometheus has no '{PROMETHEUS_JOB}' scrape job. Run: {COMPOSE} up -d --force-recreate prometheus")
    except (HTTPError, URLError, OSError, KeyError) as exc:
        problems.append(f"Prometheus not reachable at {stack.prometheus} ({exc}).")
    if problems:
        print("Not ready:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default=f"http://localhost:{os.getenv('BACKEND_PORT', '8001')}")
    parser.add_argument("--alertmanager", default="http://localhost:9093")
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--events-token", default=os.getenv("OPS_SIGNALS_EVENTS_TOKEN") or os.getenv("OPS_SIGNALS_API_TOKEN"))
    args = parser.parse_args()
    stack = Stack(args.backend.rstrip("/"), args.alertmanager.rstrip("/"), args.prometheus.rstrip("/"), args.events_token)

    _serve(METRICS_PORT, MetricsHandler, "demo metrics")
    _serve(SLACK_PORT, QuietSlackHandler, "Slack lookalike")
    _preflight(stack)
    print(f"Demo metrics on :{METRICS_PORT} (Prometheus job '{PROMETHEUS_JOB}', every 5s)")
    print(f"Slack lookalike: http://localhost:{SLACK_PORT}")
    print(f"Ops Signals UI:  http://localhost:{os.getenv('FRONTEND_PORT', '5174')}  (Findings show the same pod breakdown)")

    while True:
        warm = max(0, int(WARMUP_SECONDS - (time.time() - DEMO.started_at)))
        print("\n" + ("Ready." if not warm else f"Building metric history: ready in {warm}s (you can pick now; it waits)."))
        for key, (scenario, label, _) in SCENARIOS.items():
            print(f"  {key}  {label}{'   [done]' if scenario in DEMO.done else ''}")
        print("  r  Resolve the alerts fired so far")
        print("  q  Quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            stack.resolve_all()
            continue
        if choice not in SCENARIOS:
            continue
        scenario, _, run = SCENARIOS[choice]
        if scenario in DEMO.done:
            print("Already run. Restart the script to run it again (its pods stay changed).")
            continue
        try:
            run(stack)
            DEMO.done.add(scenario)
        except (HTTPError, URLError, OSError) as exc:
            print(f"  Failed: {exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
