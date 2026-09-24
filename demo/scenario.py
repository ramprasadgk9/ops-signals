"""The demo incident, as data: one definition shared by the history backfill, the live metrics
target and the seeder, so Prometheus history, the live scrape and the seeded events agree.

Story: checkout-api p95 latency sits around 180ms, deploy v2.14.0 lands, and three minutes later
latency steps up to about 320ms and stays there. Three weeks earlier the same thing happened after
deploy v2.9.0; that incident was resolved by a rollback and is seeded as a past case.

Standard library only - it runs in plain python:alpine containers as well as the backend image.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICE = "checkout-api"
ENV = "prod"
LATENCY_METRIC = "request_latency_p95"
RPS_METRIC = "http_requests_per_second"

# Prometheus attaches these to every scraped sample, so the backfilled history must carry the same
# values or it becomes a second series next to the live one.
SCRAPE_JOB = "checkout-api"
SCRAPE_INSTANCE = "demo-metrics:9102"

BASELINE_LATENCY_MS = 180.0
SHIFTED_LATENCY_MS = 320.0
BASELINE_RPS = 420.0

STEP_SECONDS = 15  # matches the demo Prometheus scrape_interval
HISTORY_HOURS = 7  # alert enrichment looks back 6h by default
SHIFT_MINUTES_AGO = 25
DEPLOY_MINUTES_BEFORE_SHIFT = 3

CURRENT_DEPLOY_VERSION = "v2.14.0"
PREVIOUS_DEPLOY_VERSION = "v2.13.2"
PAST_INCIDENT_DAYS_AGO = 21
PAST_DEPLOY_VERSION = "v2.9.0"

STATE_FILE = "state.json"
HISTORY_FILE = "history.om"


def _noise(t: float, salt: str, sigma: float) -> float:
    # Seeded per timestamp so the same instant always gets the same value (a rerun of the backfill,
    # or the live target scraped twice in one step, never disagrees with itself).
    return random.Random(f"{salt}:{int(t) // STEP_SECONDS}").gauss(0.0, sigma)


def latency_ms(t: float, shift_at: float | None) -> float:
    """p95 latency at unix time `t`. `shift_at=None` means the shift already happened."""
    value = BASELINE_LATENCY_MS + 10.0 * math.sin(2 * math.pi * t / 5400.0) + _noise(t, "latency", 5.0)
    if shift_at is None or t >= shift_at:
        # A short ramp rather than a perfect step: rollouts take a minute to reach every pod.
        progress = 1.0 if shift_at is None else min(1.0, (t - shift_at) / 90.0)
        value += (SHIFTED_LATENCY_MS - BASELINE_LATENCY_MS) * progress
    return max(1.0, value)


def rps(t: float) -> float:
    return max(1.0, BASELINE_RPS + 45.0 * math.sin(2 * math.pi * t / 7200.0) + _noise(t, "rps", 8.0))


def labels(extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"service": SERVICE, "env": ENV, **(extra or {})}


def format_labels(values: dict[str, str]) -> str:
    return ",".join(f'{key}="{value}"' for key, value in values.items())


# --- timeline ---------------------------------------------------------------------------------


def new_timeline(now: datetime | None = None) -> dict[str, str]:
    anchor = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    shift_at = anchor - timedelta(minutes=SHIFT_MINUTES_AGO)
    return {
        "anchor": anchor.isoformat(),
        "shift_at": shift_at.isoformat(),
        "deploy_at": (shift_at - timedelta(minutes=DEPLOY_MINUTES_BEFORE_SHIFT)).isoformat(),
        "previous_deploy_at": (anchor - timedelta(hours=26)).isoformat(),
        "history_start": (anchor - timedelta(hours=HISTORY_HOURS)).isoformat(),
    }


def read_timeline(state_dir: Path) -> dict[str, str] | None:
    path = state_dir / STATE_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_timeline(state_dir: Path, timeline: dict[str, str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STATE_FILE).write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


# --- past incident (seeded as a resolved case) ------------------------------------------------


def past_incident_csv(anchor: datetime) -> str:
    """6h of 30s points ending three weeks before `anchor`, with the same shape of shift 1h before the
    end (the rollback landed right after the window closes)."""
    end = anchor - timedelta(days=PAST_INCIDENT_DAYS_AGO)
    start = end - timedelta(hours=6)
    shift_at = past_incident_times(anchor)["shift_at"].timestamp()
    rows = ["timestamp,metric_name,value,service,env"]
    t = start.timestamp()
    while t <= end.timestamp():
        value = latency_ms(t, shift_at) - 5.0  # slightly different baseline than today
        stamp = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(f"{stamp},{LATENCY_METRIC},{value:.3f},{SERVICE},{ENV}")
        t += 30
    return "\n".join(rows) + "\n"


def past_incident_times(anchor: datetime) -> dict[str, datetime]:
    end = anchor - timedelta(days=PAST_INCIDENT_DAYS_AGO)
    shift_at = end - timedelta(hours=1)
    return {
        "deploy_at": shift_at - timedelta(minutes=4),
        "shift_at": shift_at,
        "detected_at": shift_at + timedelta(minutes=12),
        "resolved_at": shift_at + timedelta(minutes=58),
    }
