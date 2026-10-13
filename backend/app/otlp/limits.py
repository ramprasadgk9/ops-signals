"""Volume and cardinality guardrails for OTLP push ingestion.

OTLP is the first always-on, sender-controlled-volume ingestion path in this codebase - CSV is a
one-time upload and Prometheus is an on-demand pull the app itself paces, so neither needed this.
Three independent caps here, each guarding a different failure mode; see
docs/design/otlp-metrics-ingestion-plan.md §6 for the full rationale. All are in-process only, matching
this app's existing documented single-backend-instance assumption
(backend/app/autonomous/scheduler.py) - not a distributed rate limit or cardinality store.
"""

from __future__ import annotations

import os
import threading
import time


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


MAX_OTLP_BYTES = _env_int("OPS_SIGNALS_MAX_OTLP_BYTES", 10 * 1024 * 1024)
MAX_POINTS_PER_MIN = _env_int("OPS_SIGNALS_OTLP_MAX_POINTS_PER_MIN", 60_000)
MAX_SERIES_PER_METRIC = _env_int("OPS_SIGNALS_OTLP_MAX_SERIES_PER_METRIC", 2_000)
MAX_BACKLOG_PER_CYCLE = _env_int("OPS_SIGNALS_OTLP_MAX_BACKLOG_PER_CYCLE", 5_000)

# A Collector sends a few points per series every 10-60s, while analyzers need 30-80 points to judge
# a series. So a series' points wait until the oldest has waited this long (or a batch this large
# arrives at once, as a backfill does), and each analysis also reads the series' stored history.
OTLP_ANALYSIS_INTERVAL_MINUTES = _env_int("OPS_SIGNALS_OTLP_ANALYSIS_INTERVAL_MINUTES", 10)
OTLP_IMMEDIATE_BATCH_POINTS = _env_int("OPS_SIGNALS_OTLP_IMMEDIATE_BATCH_POINTS", 60)
OTLP_HISTORY_HOURS = _env_int("OPS_SIGNALS_OTLP_HISTORY_HOURS", 6)


class RateLimiter:
    """Fixed-window global point-rate limiter, checked once per request before any DB write."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._count = 0

    def try_consume(self, n: int) -> bool:
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 60:
                self._window_start = now
                self._count = 0
            if self._count + n > self.limit_per_minute:
                return False
            self._count += n
            return True


class CardinalityTracker:
    """Tracks distinct (metric_name, attribute-set) combinations seen since process start.
    Resets on restart - an accepted limitation for a single-instance deployment, not a correctness
    bug; see docs/design/otlp-metrics-ingestion-plan.md."""

    def __init__(self, max_series_per_metric: int) -> None:
        self.max_series_per_metric = max_series_per_metric
        self._lock = threading.Lock()
        self._series: dict[str, set[frozenset[tuple[str, str]]]] = {}

    def allow(self, metric_name: str, attributes: dict[str, str]) -> bool:
        signature = frozenset(attributes.items())
        with self._lock:
            known = self._series.setdefault(metric_name, set())
            if signature in known:
                return True
            if len(known) >= self.max_series_per_metric:
                return False
            known.add(signature)
            return True


rate_limiter = RateLimiter(MAX_POINTS_PER_MIN)
cardinality_tracker = CardinalityTracker(MAX_SERIES_PER_METRIC)
