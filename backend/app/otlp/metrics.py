"""Self-observability for the OTLP ingestion pipeline, exposed at GET /api/metrics.

A tool whose pitch is "explain what's happening, don't just show a number" should apply that
standard to its own ingestion path. Prometheus exposition format, not a bespoke JSON endpoint,
because this project's actual audience already runs Prometheus (it's one of the two existing data
sources) - a standard scrape target means zero new tooling on their end. See
docs/otlp-metrics-ingestion-plan.md §7.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest

REGISTRY = CollectorRegistry()

OTLP_POINTS_RECEIVED_TOTAL = Counter(
    "otlp_points_received_total",
    "OTLP metric data points accepted and queued for analysis",
    registry=REGISTRY,
)

OTLP_POINTS_REJECTED_TOTAL = Counter(
    "otlp_points_rejected_total",
    "OTLP metric data points rejected, by reason",
    ["reason"],  # rate_limit | cardinality_limit | unsupported_type | missing_value
    registry=REGISTRY,
)

OTLP_ANALYSIS_CYCLE_DURATION_SECONDS = Gauge(
    "otlp_analysis_cycle_duration_seconds",
    "Duration of the most recently completed OTLP backlog analysis cycle",
    registry=REGISTRY,
)

OTLP_ANALYSIS_CYCLE_GROUPS_PROCESSED = Gauge(
    "otlp_analysis_cycle_groups_processed",
    "Number of (service, metric_name) groups analyzed in the most recent OTLP backlog cycle",
    registry=REGISTRY,
)


def _otlp_backlog_size() -> int:
    # Imported lazily: this module is imported early (from backend/app/api/otlp.py at router
    # registration time), before the DB engine is guaranteed initialized by the FastAPI lifespan.
    # set_function's callback only runs at scrape time, by which point the engine is up.
    from sqlalchemy import func, select

    from backend.app.models.db import get_session_local
    from backend.app.models.entities import OtlpPendingPointEntity

    session_local = get_session_local()
    with session_local() as db:
        return db.execute(select(func.count()).select_from(OtlpPendingPointEntity)).scalar_one()


OTLP_BACKLOG_SIZE = Gauge(
    "otlp_backlog_size",
    "Rows received via OTLP push not yet claimed by an analysis run",
    registry=REGISTRY,
)
OTLP_BACKLOG_SIZE.set_function(_otlp_backlog_size)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def snapshot() -> dict[str, object]:
    """JSON-friendly summary of the same counters as render_metrics(), for the Settings page card
    - a plain fetch()able shape instead of a Prometheus-format text scrape. Reads the registry's
    public collect() API rather than each metric object's internal value, so this stays correct if
    metrics are ever added/renamed without a matching edit here."""
    received_total = 0.0
    rejected_by_reason: dict[str, float] = {}
    backlog_size = 0.0
    last_cycle_duration_seconds = 0.0
    last_cycle_groups_processed = 0.0

    for metric_family in REGISTRY.collect():
        for sample in metric_family.samples:
            if sample.name == "otlp_points_received_total":
                received_total = sample.value
            elif sample.name == "otlp_points_rejected_total":
                rejected_by_reason[sample.labels.get("reason", "unknown")] = sample.value
            elif sample.name == "otlp_backlog_size":
                backlog_size = sample.value
            elif sample.name == "otlp_analysis_cycle_duration_seconds":
                last_cycle_duration_seconds = sample.value
            elif sample.name == "otlp_analysis_cycle_groups_processed":
                last_cycle_groups_processed = sample.value

    return {
        "points_received_total": received_total,
        "points_rejected_total": rejected_by_reason,
        "backlog_size": backlog_size,
        "last_analysis_cycle_duration_seconds": last_cycle_duration_seconds,
        "last_analysis_cycle_groups_processed": last_cycle_groups_processed,
    }
