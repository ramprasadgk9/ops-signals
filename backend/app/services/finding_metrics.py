"""Active findings as Prometheus metrics, on GET /api/metrics (docs/finding-metrics.md).

Prometheus scrapes them like any other target, so a team can alert on "strong evidence on checkout"
with an ordinary alert rule and route it with Alertmanager, or chart findings on any dashboard.

Counted the way the Overview page counts active findings (services/active_findings.py): a problem
every run sees again is one finding, and it stops counting when a case on it is closed or it falls
out of the window. Labels are kept few on purpose (no finding id, no pod), and the number of series
is capped, so this can't add much to anyone's Prometheus.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from prometheus_client import CollectorRegistry
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import FindingMetricsConfig, get_finding_metrics_config
from backend.app.models.entities import FindingEntity
from backend.app.services.active_findings import active_findings, problem_of
from backend.app.services.finding_trust import finding_trust

logger = logging.getLogger(__name__)

LABELS = ("service", "metric", "cluster", "evidence", "severity")
# Which series to keep when there are more than max_series: the ones most worth alerting on.
_EVIDENCE_RANK = {"strong": 0, "team_confirmed": 1, "data_problem": 2, "moderate": 3, "context": 4}
_SEVERITY_RANK = {"critical": 0, "significant": 1, "normal": 2}

SeriesKey = tuple[str, str, str, str, str]


@dataclass
class FindingCounts:
    series: dict[SeriesKey, int] = field(default_factory=dict)
    dropped: int = 0
    ok: bool = True


def _label(value: str | None, default: str) -> str:
    value = (value or "").strip()
    return value or default


def count_active_findings(db: Session, config: FindingMetricsConfig, now: datetime | None = None) -> FindingCounts:
    """Active findings per (service, metric, cluster, evidence, severity), each problem once, as its
    newest finding describes it."""
    now = now or datetime.now(timezone.utc)
    findings = db.execute(select(FindingEntity).where(FindingEntity.created_at >= now - timedelta(hours=config.window_hours))).scalars().all()
    newest: dict[int | None, FindingEntity] = {}
    for finding in active_findings(db, findings):
        current = newest.get(problem_of(finding))
        if current is None or (finding.created_at, finding.id) > (current.created_at, current.id):
            newest[problem_of(finding)] = finding
    trust = finding_trust(db, list(newest.values()))

    counts: Counter[SeriesKey] = Counter()
    for finding in newest.values():
        entry = trust.get(finding.id) or {}
        evidence = (entry.get("badge") or "context") if entry.get("tier") == "needs_attention" else "context"
        counts[(
            _label(finding.service, "unknown"),
            finding.metric_name,
            _label(finding.cluster, ""),
            evidence,
            _label(finding.health_status, "unknown").lower(),
        )] += 1

    ranked = sorted(counts.items(), key=lambda item: (_EVIDENCE_RANK.get(item[0][3], 9), _SEVERITY_RANK.get(item[0][4], 9), -item[1], item[0]))
    kept = dict(ranked[: config.max_series])
    return FindingCounts(series=kept, dropped=sum(count for _, count in ranked[config.max_series :]))


def _default_counts(config: FindingMetricsConfig) -> FindingCounts:
    # Imported lazily, as in otlp/metrics.py: the engine is set up by the app lifespan, after import.
    from backend.app.models.db import get_session_local

    with get_session_local()() as db:
        return count_active_findings(db, config)


class ActiveFindingsCollector(Collector):
    def __init__(
        self,
        load: Callable[[FindingMetricsConfig], FindingCounts] = _default_counts,
        config: Callable[[], FindingMetricsConfig] = get_finding_metrics_config,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._load = load
        self._config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: tuple[float, FindingCounts] | None = None

    def _counts(self, config: FindingMetricsConfig) -> FindingCounts:
        with self._lock:
            now = self._clock()
            if self._cached is not None and now - self._cached[0] < config.cache_seconds:
                return self._cached[1]
            try:
                counts = self._load(config)
            except Exception:
                # A database outage must not break the scrape of the other metrics on this endpoint.
                logger.warning("Could not count active findings for /api/metrics", exc_info=True)
                counts = FindingCounts(ok=False)
            self._cached = (now, counts)
            return counts

    def collect(self) -> Iterator[GaugeMetricFamily]:
        config = self._config()
        if not config.enabled:
            return
        counts = self._counts(config)
        active = GaugeMetricFamily(
            "ops_signals_active_findings",
            "Active findings, each problem counted once, as on the Overview page. evidence is strong, moderate, "
            "data_problem or team_confirmed for findings that need attention, context for the rest.",
            labels=LABELS,
        )
        for key, count in sorted(counts.series.items()):
            active.add_metric(list(key), count)
        yield active
        yield GaugeMetricFamily(
            "ops_signals_active_findings_dropped",
            "Active findings left out of ops_signals_active_findings because of the series cap (OPS_SIGNALS_FINDING_METRICS_MAX_SERIES)",
            value=counts.dropped,
        )
        yield GaugeMetricFamily(
            "ops_signals_active_findings_up",
            "1 when the active findings could be counted on this scrape, 0 when the database could not be read",
            value=1 if counts.ok else 0,
        )


REGISTRY = CollectorRegistry()
REGISTRY.register(ActiveFindingsCollector())
