"""The demo story, as data: one definition shared by the history backfill, the live metrics target,
the OTLP sender and the seeder, so Prometheus history, the live data and the seeded history agree.

Four services of one online shop, each showing different features (docs/demo.md):

- checkout-api (Prometheus): p95 latency sits around 180ms, CI deploy v2.14.0 lands, and three
  minutes later latency steps up to about 320ms. Five weeks earlier the same happened after
  v2.9.0; that case was fixed by a rollback and published with a write-up.
- payments-db (Prometheus): connection wait and active connections climb together (the shipped
  pool_exhaustion pattern). The pool ran out three times before; the last fix, 9 days ago, raised
  the pool size and left the leak open, so this is the fix that didn't stick.
- search-svc (Prometheus): a new version shows up on search_build_info with no CI event (a deploy
  found automatically), then latency and errors jump together (latency_error_cascade) and the index
  merge backlog grows (a metric the wording file doesn't describe).
- orders (OTLP): the failed-orders counter's rate steps up after CI deploy v3.2.0 and a case is
  being worked on. A short processing slowdown is analyzed with the orders team's own settings
  (demo/config/analyzer-overrides/).

Standard library only - it runs in plain python:alpine containers as well as the backend image.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ENV = "prod"

# Prometheus attaches these to every scraped sample, so the backfilled history must carry the same
# values or it becomes a second series next to the live one.
SCRAPE_JOB = "demo-shop"
SCRAPE_INSTANCE = "demo-metrics:9102"

STEP_SECONDS = 15  # matches the demo Prometheus scrape_interval
HISTORY_HOURS = 7  # alert enrichment and the scheduled analysis look back 6h

STATE_FILE = "state.json"
HISTORY_FILE = "history.om"

# --- checkout-api: the deploy that broke it ---------------------------------------------------

SERVICE = "checkout-api"
LATENCY_METRIC = "request_latency_p95"
RPS_METRIC = "http_requests_per_second"

BASELINE_LATENCY_MS = 180.0
SHIFTED_LATENCY_MS = 320.0
BASELINE_RPS = 420.0

# Far enough back that the shift is unmistakable in the 6h analysis window whatever the wave and
# noise are doing: at 25 minutes about 1 run in 3 read it as a trend instead (no change point, so
# the deploy was matched against the alert time); from 35 minutes on it's detected every time.
SHIFT_MINUTES_AGO = 45
DEPLOY_MINUTES_BEFORE_SHIFT = 3

CURRENT_DEPLOY_VERSION = "v2.14.0"
PREVIOUS_DEPLOY_VERSION = "v2.13.2"
# More than 30 days back, so today's problem (a different deploy) doesn't read as the rollback
# failing to hold (backend/app/memory/fix_came_back.py).
PAST_INCIDENT_DAYS_AGO = 35
PAST_DEPLOY_VERSION = "v2.9.0"

# --- payments-db: the fix that didn't stick ---------------------------------------------------

PAYMENTS_SERVICE = "payments-db"
# The metric names the shipped pool_exhaustion rule reads (config/behavior_definitions.d/core.yml).
DB_WAIT_METRIC = "db_connection_wait_seconds"
DB_ACTIVE_METRIC = "db_connections_active"
PAYMENTS_SHIFT_MINUTES_AGO = 60
# The earlier times the pool ran out, oldest first. The last one is within 30 days, so today's
# problem counts as coming back after its fix (backend/app/memory/fix_came_back.py).
PAYMENTS_PAST_DAYS_AGO = (40, 25, 9)

# --- search-svc: the deploy nobody announced --------------------------------------------------

SEARCH_SERVICE = "search-svc"
ERROR_RATE_METRIC = "error_rate"
BACKLOG_METRIC = "search_index_merge_backlog"
BUILD_INFO_METRIC = "search_build_info"
SEARCH_OLD_VERSION = "1.8.0"
SEARCH_NEW_VERSION = "1.9.0"
SEARCH_DEPLOY_MINUTES_AGO = 35
SEARCH_SHIFT_MINUTES_AGO = 30
SEARCH_PAST_DAYS_AGO = 2

# --- orders (OTLP): a case being worked on ----------------------------------------------------

ORDERS_SERVICE = "orders"
ORDERS_FAILED_METRIC = "orders_failed"  # a cumulative counter; Ops Signals analyzes its rate
ORDERS_DURATION_METRIC = "orders_processing_seconds"
ORDERS_DEPLOY_VERSION = "v3.2.0"
ORDERS_SHIFT_MINUTES_AGO = 90
ORDERS_DEPLOY_MINUTES_BEFORE_SHIFT = 4
ORDERS_STEP_SECONDS = 30
ORDERS_HISTORY_HOURS = 6.5
ORDERS_BASELINE_FAILED_PER_SECOND = 0.08
ORDERS_SHIFTED_FAILED_PER_SECOND = 1.1
ORDERS_SLOWDOWN_MINUTES_AGO = 20
ORDERS_SLOWDOWN_SECONDS = 180


# --- shapes ------------------------------------------------------------------------------------


def _noise(t: float, salt: str, sigma: float, step: int = STEP_SECONDS) -> float:
    # Seeded per timestamp so the same instant always gets the same value (a rerun of the backfill,
    # or the live target scraped twice in one step, never disagrees with itself).
    return random.Random(f"{salt}:{int(t) // step}").gauss(0.0, sigma)


def _wave(t: float, period_seconds: float, amplitude: float) -> float:
    return amplitude * math.sin(2 * math.pi * t / period_seconds)


def _progress(t: float, start: float | None, ramp_seconds: float) -> float:
    """0 before `start`, rising to 1 over `ramp_seconds`. `start=None` means long ago."""
    if start is None:
        return 1.0
    if t < start:
        return 0.0
    return min(1.0, (t - start) / ramp_seconds)


def latency_ms(t: float, shift_at: float | None) -> float:
    """checkout-api p95 latency at unix time `t`. `shift_at=None` means the shift already happened."""
    value = BASELINE_LATENCY_MS + _wave(t, 5400.0, 10.0) + _noise(t, "latency", 5.0)
    # A short ramp rather than a perfect step: rollouts take a minute to reach every pod.
    value += (SHIFTED_LATENCY_MS - BASELINE_LATENCY_MS) * _progress(t, shift_at, 90.0)
    return max(1.0, value)


def rps(t: float) -> float:
    return max(1.0, BASELINE_RPS + _wave(t, 7200.0, 45.0) + _noise(t, "rps", 8.0))


def db_wait_seconds(t: float, shift_at: float | None) -> float:
    """payments-db connection wait: a few ms, then a climb over 20 minutes as the pool runs out."""
    value = 0.012 + _wave(t, 6000.0, 0.002) + _noise(t, "db-wait", 0.0015)
    value += 0.43 * _progress(t, shift_at, 1200.0) + _noise(t, "db-wait-hot", 0.03) * _progress(t, shift_at, 1200.0)
    return max(0.001, value)


def db_active_connections(t: float, shift_at: float | None) -> float:
    """payments-db active connections out of a pool of 40: about 13, then pinned near the top."""
    value = 13.0 + _wave(t, 6000.0, 2.0) + _noise(t, "db-active", 0.8)
    value += 25.0 * _progress(t, shift_at, 900.0)
    return max(0.0, min(40.0, value))


def search_latency_ms(t: float, shift_at: float | None) -> float:
    """search-svc p95 latency: about 90ms, then jumpy and several times higher."""
    value = 90.0 + _wave(t, 4800.0, 6.0) + _noise(t, "search-latency", 4.0)
    hot = _progress(t, shift_at, 60.0)
    return max(1.0, value + hot * (300.0 + abs(_noise(t, "search-latency-hot", 120.0))))


def search_error_rate(t: float, shift_at: float | None) -> float:
    """search-svc share of failed requests, in percent: about 0.2%, then several percent."""
    value = 0.2 + abs(_noise(t, "search-errors", 0.05))
    hot = _progress(t, shift_at, 60.0)
    return value + hot * (3.5 + abs(_noise(t, "search-errors-hot", 1.5)))


def search_backlog(t: float, shift_at: float | None) -> float:
    """search-svc index segments waiting to merge: steady, then growing since the new version."""
    value = 120.0 + _wave(t, 3600.0, 15.0) + _noise(t, "search-backlog", 6.0)
    if shift_at is not None and t > shift_at:
        value += (t - shift_at) * 1.1
    return max(0.0, value)


def orders_failed_total(t: float, start: float, shift_at: float) -> int:
    """The orders failed-orders counter, cumulative since `start`: its rate steps up at `shift_at`."""
    elapsed = max(0.0, t - start)
    extra = max(0.0, t - shift_at)
    wobble = 0.5 * math.sin(2 * math.pi * t / 1800.0) + 0.5  # keeps the rate from being perfectly flat
    total = ORDERS_BASELINE_FAILED_PER_SECOND * elapsed
    total += (ORDERS_SHIFTED_FAILED_PER_SECOND - ORDERS_BASELINE_FAILED_PER_SECOND) * extra
    return int(total + 3 * wobble)


def orders_processing_seconds(t: float, slow_at: float) -> float:
    """How long an order takes to process: steady, apart from a 3-minute slowdown at `slow_at`. The
    orders team's own settings cover this metric, so its finding carries "Custom settings"."""
    value = 0.42 + _wave(t, 5400.0, 0.03) + _noise(t, "orders-duration", 0.02, ORDERS_STEP_SECONDS)
    if slow_at <= t < slow_at + ORDERS_SLOWDOWN_SECONDS:
        value += 0.18
    return max(0.05, value)


# --- the Prometheus series ---------------------------------------------------------------------


@dataclass(frozen=True)
class Series:
    name: str
    help: str
    labels: dict[str, str]
    value_at: Callable[[float], float | None]  # None = no sample at that time


def labels(service: str = SERVICE, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"service": service, "env": ENV, **(extra or {})}


def format_labels(values: dict[str, str]) -> str:
    return ",".join(f'{key}="{value}"' for key, value in values.items())


def prometheus_series(timeline: dict[str, str]) -> list[Series]:
    """Every series the demo scrape target serves, in OpenMetrics family order (one name together)."""
    at = {key: parse_time(value).timestamp() for key, value in timeline.items()}
    checkout_shift = at["shift_at"]
    payments_shift = at["payments_shift_at"]
    search_deploy = at["search_deploy_at"]
    search_shift = at["search_shift_at"]

    def build_info(version: str, before_deploy: bool) -> Callable[[float], float | None]:
        return lambda t: 1.0 if (t < search_deploy) == before_deploy else None

    return [
        Series(LATENCY_METRIC, "p95 request latency in milliseconds", labels(SERVICE),
               lambda t: latency_ms(t, checkout_shift)),
        Series(LATENCY_METRIC, "p95 request latency in milliseconds", labels(SEARCH_SERVICE),
               lambda t: search_latency_ms(t, search_shift)),
        Series(RPS_METRIC, "requests per second", labels(SERVICE), rps),
        Series(DB_WAIT_METRIC, "time a query waited for a pooled connection, in seconds", labels(PAYMENTS_SERVICE),
               lambda t: db_wait_seconds(t, payments_shift)),
        Series(DB_ACTIVE_METRIC, "connections in use, out of a pool of 40", labels(PAYMENTS_SERVICE),
               lambda t: db_active_connections(t, payments_shift)),
        Series(ERROR_RATE_METRIC, "failed requests, in percent", labels(SEARCH_SERVICE),
               lambda t: search_error_rate(t, search_shift)),
        Series(BACKLOG_METRIC, "index segments waiting to be merged", labels(SEARCH_SERVICE),
               lambda t: search_backlog(t, search_shift)),
        # How most apps report their version; deploy discovery reads it (docs/deploy-discovery.md).
        Series(BUILD_INFO_METRIC, "running version", labels(SEARCH_SERVICE, {"version": SEARCH_OLD_VERSION}),
               build_info(SEARCH_OLD_VERSION, before_deploy=True)),
        Series(BUILD_INFO_METRIC, "running version", labels(SEARCH_SERVICE, {"version": SEARCH_NEW_VERSION}),
               build_info(SEARCH_NEW_VERSION, before_deploy=False)),
    ]


# --- timeline ---------------------------------------------------------------------------------


def new_timeline(now: datetime | None = None) -> dict[str, str]:
    anchor = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    shift_at = anchor - timedelta(minutes=SHIFT_MINUTES_AGO)
    orders_shift_at = anchor - timedelta(minutes=ORDERS_SHIFT_MINUTES_AGO)
    return {
        "anchor": anchor.isoformat(),
        "shift_at": shift_at.isoformat(),
        "deploy_at": (shift_at - timedelta(minutes=DEPLOY_MINUTES_BEFORE_SHIFT)).isoformat(),
        "previous_deploy_at": (anchor - timedelta(hours=26)).isoformat(),
        "history_start": (anchor - timedelta(hours=HISTORY_HOURS)).isoformat(),
        "payments_shift_at": (anchor - timedelta(minutes=PAYMENTS_SHIFT_MINUTES_AGO)).isoformat(),
        "search_deploy_at": (anchor - timedelta(minutes=SEARCH_DEPLOY_MINUTES_AGO)).isoformat(),
        "search_shift_at": (anchor - timedelta(minutes=SEARCH_SHIFT_MINUTES_AGO)).isoformat(),
        "orders_shift_at": orders_shift_at.isoformat(),
        "orders_deploy_at": (orders_shift_at - timedelta(minutes=ORDERS_DEPLOY_MINUTES_BEFORE_SHIFT)).isoformat(),
        "orders_history_start": (anchor - timedelta(hours=ORDERS_HISTORY_HOURS)).isoformat(),
        "orders_slow_at": (anchor - timedelta(minutes=ORDERS_SLOWDOWN_MINUTES_AGO)).isoformat(),
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


# --- past problems (seeded as findings and cases) ----------------------------------------------


@dataclass(frozen=True)
class PastIncident:
    """A problem that happened before today, analyzed from a CSV and (with a case) resolved."""

    key: str
    service: str
    metric: str
    days_ago: float
    value_at: Callable[[float, float], float]  # (t, shift_at) -> value
    # More metrics analyzed in the same run (one CSV), so multi-metric patterns can match.
    extra_metrics: tuple[tuple[str, Callable[[float, float], float]], ...] = ()
    deploy_version: str | None = None
    case: dict[str, dict[str, object]] | None = None  # investigation / rca / resolution / writeup
    detected_after_minutes: int = 12
    resolved_after_minutes: int = 58

    def times(self, anchor: datetime) -> dict[str, datetime]:
        end = anchor - timedelta(days=self.days_ago)
        shift_at = end - timedelta(hours=1)
        return {
            "start": end - timedelta(hours=6),
            "end": end,
            "deploy_at": shift_at - timedelta(minutes=4),
            "shift_at": shift_at,
            "detected_at": shift_at + timedelta(minutes=self.detected_after_minutes),
            "resolved_at": shift_at + timedelta(minutes=self.resolved_after_minutes),
        }

    def csv(self, anchor: datetime) -> str:
        """6h of 30s points ending `days_ago` before `anchor`, with the problem starting 1h before
        the end (the fix landed right after the window closes)."""
        times = self.times(anchor)
        shift_at = times["shift_at"].timestamp()
        rows = ["timestamp,metric_name,value,service,env"]
        for metric, value_at in ((self.metric, self.value_at), *self.extra_metrics):
            t = times["start"].timestamp()
            while t <= times["end"].timestamp():
                stamp = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                rows.append(f"{stamp},{metric},{value_at(t, shift_at):.4f},{self.service},{ENV}")
                t += 30
        return "\n".join(rows) + "\n"


def _payments_case(days_ago: int, fix: str, root_cause: str, note: str) -> dict[str, dict[str, object]]:
    return {
        "investigation": {"investigation_status": "completed", "investigation_note": note},
        "rca": {
            "root_cause_status": "confirmed",
            "root_cause_summary": root_cause,
            "root_cause_confidence": 0.8,
            "root_cause_verified": True,
        },
        "resolution": {
            "outcome_status": "resolved",
            "outcome_summary": f"Connection wait back to a few milliseconds after the fix ({days_ago} days ago).",
            "corrective_action": fix,
            "learning_outcome_status": "confirmed",
            "root_cause_category": "resource exhaustion",
            "resolved_by": "db-oncall",
        },
    }


PAST_INCIDENTS: list[PastIncident] = [
    # First, so it's case #1 (scripts/demo_smoke_test.py checks /api/cases/1).
    PastIncident(
        key="checkout-rollback",
        service=SERVICE,
        metric=LATENCY_METRIC,
        days_ago=PAST_INCIDENT_DAYS_AGO,
        value_at=lambda t, shift_at: latency_ms(t, shift_at) - 5.0,  # slightly different baseline than today
        deploy_version=PAST_DEPLOY_VERSION,
        case={
            "investigation": {
                "investigation_status": "completed",
                "investigation_note": (
                    f"p95 latency on {SERVICE} stepped from ~175ms to ~310ms four minutes after deploy "
                    f"{PAST_DEPLOY_VERSION}. Traces show every checkout request making an extra synchronous "
                    "call to the catalog service for pricing."
                ),
            },
            "rca": {
                "root_cause_status": "confirmed",
                "root_cause_summary": (
                    f"Deploy {PAST_DEPLOY_VERSION} added a synchronous per-item catalog lookup to the checkout "
                    "request path, raising p95 latency by ~130ms."
                ),
                "root_cause_confidence": 0.9,
                "root_cause_verified": True,
            },
            "resolution": {
                "outcome_status": "resolved",
                "outcome_summary": f"Rolled back {PAST_DEPLOY_VERSION}; p95 latency returned to baseline within 5 minutes.",
                "corrective_action": "Roll back the deploy, then batch the catalog lookups before re-releasing.",
                "learning_outcome_status": "confirmed",
                "root_cause_category": "deploy regression",
                "resolved_by": "oncall",
            },
            "writeup": {
                "writeup": (
                    "## Checkout latency after a deploy\n\n"
                    f"**What happened.** Four minutes after deploy {PAST_DEPLOY_VERSION}, checkout-api p95 latency "
                    "went from about 175ms to about 310ms and stayed there.\n\n"
                    "**Why.** The release added a synchronous catalog lookup for every item in the cart.\n\n"
                    f"**What fixed it.** Rolling back {PAST_DEPLOY_VERSION}; latency was back to normal within 5 "
                    "minutes. The lookups were batched before the change was released again.\n\n"
                    "**Next time.** If checkout latency steps up right after a deploy, roll back first and "
                    "look at new calls on the request path."
                )
            },
        },
    ),
    PastIncident(
        key="payments-restart",
        service=PAYMENTS_SERVICE,
        metric=DB_WAIT_METRIC,
        days_ago=PAYMENTS_PAST_DAYS_AGO[0],
        value_at=db_wait_seconds,
        extra_metrics=((DB_ACTIVE_METRIC, db_active_connections),),
        case=_payments_case(
            PAYMENTS_PAST_DAYS_AGO[0],
            fix="Restarted the payments pods to release the stuck connections.",
            root_cause="Connections were not returned to the pool; the restart released them.",
            note="Queries waited up to half a second for a connection; all 40 pool connections were busy.",
        ),
    ),
    PastIncident(
        key="payments-timeout",
        service=PAYMENTS_SERVICE,
        metric=DB_WAIT_METRIC,
        days_ago=PAYMENTS_PAST_DAYS_AGO[1],
        value_at=db_wait_seconds,
        extra_metrics=((DB_ACTIVE_METRIC, db_active_connections),),
        case=_payments_case(
            PAYMENTS_PAST_DAYS_AGO[1],
            fix="Restarted the payments pods and lowered the idle-connection timeout to 60s.",
            root_cause="The refund worker holds connections while it waits on the bank API.",
            note="Same picture as last time: the pool was full and connection wait climbed for 20 minutes.",
        ),
    ),
    PastIncident(
        key="payments-pool-size",
        service=PAYMENTS_SERVICE,
        metric=DB_WAIT_METRIC,
        days_ago=PAYMENTS_PAST_DAYS_AGO[2],
        value_at=db_wait_seconds,
        extra_metrics=((DB_ACTIVE_METRIC, db_active_connections),),
        case=_payments_case(
            PAYMENTS_PAST_DAYS_AGO[2],
            fix=(
                "Raised the connection pool from 20 to 40. "
                "Still open: find where the refund worker leaks connections."
            ),
            root_cause="The refund worker keeps connections open during slow bank API calls; the pool was too small to absorb it.",
            note="Third time this month. Connection wait climbed to 0.4s and active connections hit the pool limit.",
        ),
    ),
    # Past search-svc findings with no case: the team answered "Was this real?" on them.
    PastIncident(
        key="search-latency",
        service=SEARCH_SERVICE,
        metric=LATENCY_METRIC,
        days_ago=SEARCH_PAST_DAYS_AGO,
        value_at=search_latency_ms,
        extra_metrics=((ERROR_RATE_METRIC, search_error_rate),),
    ),
]


def orders_case_notes() -> dict[str, dict[str, object]]:
    """The orders case, left in progress: someone is looking at it right now."""
    return {
        "investigation": {
            "investigation_status": "in_progress",
            "investigation_note": (
                f"Failed orders went from about 5 a minute to about 65 a minute four minutes after {ORDERS_DEPLOY_VERSION}. "
                "Failures are all 'address validation timeout'. Checking whether the new address "
                "provider client has a shorter timeout."
            ),
        },
        "rca": {
            "root_cause_status": "hypothesis",
            "root_cause_summary": f"{ORDERS_DEPLOY_VERSION} switched the address validation client; its default timeout may be too short.",
            "root_cause_confidence": 0.5,
        },
    }
