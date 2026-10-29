"""Recurring execution for saved autonomous policies.

No scheduler infrastructure (APScheduler, Celery, a worker container) exists anywhere in this
repo, so this is deliberately a simple in-process polling loop, not a distributed job queue. Every
backend instance polls; each due policy run is claimed in the database first
(AutonomousPolicyRepository.claim_due), so backends sharing one database never run it twice.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import Engine, func, text
from sqlalchemy.orm import Session

from backend.app.autonomous.execution import execute_autonomous_plan_once
from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
from backend.app.autonomous.repository import AutonomousPolicyRepository
from backend.app.autonomous.schemas import AnalysisScope, AutonomousRunRequest, ExecutionPolicy, MonitoringSelection
from backend.app.deploy_discovery.service import run_if_due as run_deploy_discovery_if_due
from backend.app.metric_usage.service import run_scheduled_check_if_due
from backend.app.models.db import get_engine, get_session_local
from backend.app.models.entities import AutonomousPolicyEntity, NormalizedPoint, OtlpPendingPointEntity
from backend.app.otlp.limits import (
    MAX_BACKLOG_PER_CYCLE,
    OTLP_ANALYSIS_INTERVAL_MINUTES,
    OTLP_HISTORY_HOURS,
    OTLP_IMMEDIATE_BATCH_POINTS,
)
from backend.app.otlp.metrics import OTLP_ANALYSIS_CYCLE_DURATION_SECONDS, OTLP_ANALYSIS_CYCLE_GROUPS_PROCESSED
from backend.app.services.point_retention import run_if_due as run_point_retention_if_due
from backend.app.services.prometheus_service import PrometheusQueryService, resolve_prometheus_connection
from backend.app.services.timeseries_routing_service import build_csv_routing_config

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
# Any fixed 64-bit number, unique to this lock among the app's advisory locks.
OTLP_ANALYSIS_LOCK_KEY = 7_140_020_263


def _build_run_request(policy: AutonomousPolicyEntity) -> AutonomousRunRequest:
    return AutonomousRunRequest(
        datasource=policy.datasource,
        backend=policy.backend,
        connection_id=policy.connection_id,
        scope=AnalysisScope(**policy.scope_json),
        monitoring_selection=MonitoringSelection(**policy.monitoring_categories_json),
        execution=ExecutionPolicy(**policy.execution_policy_json),
        dry_run=False,
    )


def _run_one_policy(db: Session, repo: AutonomousPolicyRepository, policy: AutonomousPolicyEntity) -> None:
    # Imported here, not at module load time, to avoid a circular import: backend.app.api.autonomous
    # imports from this package's repository/schemas modules already.
    from backend.app.api.autonomous import preview_autonomous_plan

    request = _build_run_request(policy)
    status = "failed"
    try:
        # The policy's own connection, never the default: a removed connection fails the run.
        config = resolve_prometheus_connection(policy.connection_id)
        prometheus = PrometheusQueryService(config)
        preview = preview_autonomous_plan(request, prometheus)
        result = execute_autonomous_plan_once(
            preview=preview,
            prometheus=prometheus,
            db=db,
            config=config,
            analysis_window=request.execution.analysis_window,
            step=request.execution.interval,
            dry_run=False,
            policy_id=policy.id,
            trigger="scheduled",
        )
        status = result.status
    except Exception:
        logger.exception("Scheduled autonomous run failed for policy %s (%s)", policy.id, policy.name)
    repo.record_run_result(policy.id, status=status, ran_at=datetime.now(timezone.utc))


def _run_due_policies_once() -> None:
    """Synchronous body of one scheduler tick - runs on a worker thread (see run_scheduler_loop)
    since it does the same blocking DB and Prometheus HTTP work a normal request handler does."""
    session_local = get_session_local()
    with session_local() as db:
        repo = AutonomousPolicyRepository(db)
        now = datetime.now(timezone.utc)
        for policy in repo.list_due(now=now):
            # Another backend claimed it between our list and this claim: it runs there.
            if not repo.claim_due(policy, now=now):
                continue
            _run_one_policy(db, repo, policy)


def _infer_interval(rows: list[OtlpPendingPointEntity]) -> str:
    """Derives the resample interval from this group's actual point density, instead of assuming
    a fixed cadence. OTel senders commonly export at 10s/15s/30s/60s - a hardcoded interval
    smaller than the real gap would leave normalize_timeseries()'s resample step
    (intelligence/normalize/normalizer.py) filling most buckets with NaN, diluting the signal
    analyzers see. Same principle backend/app/autonomous/execution.py already applies to
    Prometheus, deriving interval from the query's actual step_seconds rather than guessing.

    Uses total span / point count (average interval), not the median gap between consecutive
    sorted timestamps: a pending batch for one (service, metric_name) group can contain more than
    one overlapping send - e.g. several pods of the same service each exporting independently on
    their own timer - which interleaves when sorted. The gaps *between* interleaved points from
    different sends no longer reflect any single send's real cadence, and their median can come
    out far smaller than the true interval (observed in practice: two 5-minute-interval sends
    merged produced a ~20s median, upsampling a 288-point series into 4307 buckets, 87% NaN).
    Span-over-count is immune to interleaving order since it depends only on total duration and
    point count, not gap sequence."""
    timestamps = sorted({row.timestamp for row in rows})
    if len(timestamps) < 2:
        return "1m"
    span_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
    if span_seconds <= 0:
        return "1m"
    average_seconds = max(int(span_seconds / (len(timestamps) - 1)), 1)
    if average_seconds >= 60:
        return f"{max(average_seconds // 60, 1)}m"
    return f"{average_seconds}s"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _due_otlp_groups(db: Session, now: datetime) -> list[tuple[str, str, int]]:
    """(service, metric_name, pending rows) of the series worth analyzing now, oldest first.
    Analyzing every cycle would look at a minute of data each time, too little for any analyzer,
    and would repeat each finding every minute. Counted in distinct timestamps, not rows: one
    metric can send many rows per timestamp (system.cpu.time, one per CPU state)."""
    rows = (
        db.query(
            OtlpPendingPointEntity.service,
            OtlpPendingPointEntity.metric_name,
            func.min(OtlpPendingPointEntity.received_at),
            func.count(func.distinct(OtlpPendingPointEntity.timestamp)),
            func.count(),
        )
        .group_by(OtlpPendingPointEntity.service, OtlpPendingPointEntity.metric_name)
        .all()
    )
    wait = timedelta(minutes=OTLP_ANALYSIS_INTERVAL_MINUTES)
    due = [
        (oldest, service, metric_name, count)
        for service, metric_name, oldest, timestamps, count in rows
        if timestamps >= OTLP_IMMEDIATE_BATCH_POINTS or (oldest is not None and now - _as_utc(oldest) >= wait)
    ]
    due.sort(key=lambda item: _as_utc(item[0]) if item[0] is not None else now)
    return [(service, metric_name, count) for _, service, metric_name, count in due]


def _otlp_history(db: Session, service: str, metric_name: str, before: datetime) -> list[dict[str, object]]:
    """The series' points from earlier OTLP runs (stored by MetricAnalysisExecutor), so analyzers
    judge the new points against a baseline instead of only the last few minutes."""
    points = (
        db.query(NormalizedPoint)
        .filter(
            NormalizedPoint.source == "otel",
            NormalizedPoint.service == service,
            NormalizedPoint.metric_name == metric_name,
            NormalizedPoint.timestamp >= before - timedelta(hours=OTLP_HISTORY_HOURS),
            NormalizedPoint.timestamp < before,
        )
        .order_by(NormalizedPoint.timestamp)
        .all()
    )
    return [
        {
            "timestamp": _as_utc(point.timestamp),
            "metric_name": point.metric_name,
            "value": point.value,
            "service": point.service,
            "source": "otel",
            "host": point.host,
            "namespace": point.namespace,
            "pod": point.pod,
            "env": point.env,
            "metric_type": point.metric_type,
        }
        for point in points
        # Gaps are stored as NaN; normalization rejects them as input and recreates the gaps anyway.
        if point.value is not None and not math.isnan(point.value)
    ]


def _analyze_otlp_group(db: Session, service: str, metric_name: str, rows: list[OtlpPendingPointEntity]) -> None:
    new_from = min(_as_utc(row.timestamp) for row in rows)
    history = _otlp_history(db, service, metric_name, before=new_from)
    records = [
        {
            "timestamp": row.timestamp,
            "metric_name": row.metric_name,
            "value": row.value,
            "service": row.service,
            "source": "otel",
            "host": row.host,
            "namespace": row.namespace,
            "pod": row.pod,
            "env": row.env,
            "metric_type": row.metric_type,
            **{f"label_{key}": value for key, value in (row.attributes_json or {}).items()},
        }
        for row in rows
    ]

    pipeline_config = build_csv_routing_config(
        provider="otel",
        service=service,
        metric_name=metric_name,
        interval=_infer_interval(rows),
        analyzer_id="all",
        preview=False,
    )
    pipeline_config.input.source_type = "otel"
    pipeline_config.input.required_columns = ["timestamp", "metric_name", "value"]
    pipeline_config.input.provider_mappings = {}

    row_ids = [row.id for row in rows]
    try:
        MetricAnalysisExecutor(pipeline_config).execute_dataframe(
            pd.DataFrame.from_records([*history, *records]),
            run_metadata={
                "trigger": "otlp_push",
                "service": service,
                "metric_name": metric_name,
                "point_count": len(rows),
                "history_point_count": len(history),
            },
            db=db,
            # History is already stored; saving it again would double it on every run.
            persist_points_after=history[-1]["timestamp"] if history else None,
        )
        db.query(OtlpPendingPointEntity).filter(OtlpPendingPointEntity.id.in_(row_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        logger.exception(
            "OTLP analysis failed for service=%s metric_name=%s; dropping its %d new points", service, metric_name, len(row_ids)
        )
        db.rollback()
        # Kept, a batch that fails would fail again every cycle and use up the cycle budget,
        # until no series was analyzed at all. Dropped, it costs this series one interval.
        db.query(OtlpPendingPointEntity).filter(OtlpPendingPointEntity.id.in_(row_ids)).delete(synchronize_session=False)
        db.commit()


@contextmanager
def _otlp_analysis_lock(engine: Engine) -> Iterator[bool]:
    """Yields True when this backend may run the OTLP cycle: one backend at a time, since two would
    analyze the same pending points twice. A session-level lock on its own connection, because each
    group commits as it goes and a transaction-level lock would end at the first commit. Postgres
    drops it if the backend dies. SQLite serializes writers on its own."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": OTLP_ANALYSIS_LOCK_KEY}).scalar())
        # Don't sit idle in a transaction for the whole cycle; the lock outlives it.
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": OTLP_ANALYSIS_LOCK_KEY})
                conn.commit()


def _run_pending_otlp_analysis_once() -> None:
    with _otlp_analysis_lock(get_engine()) as acquired:
        # Another backend is running this cycle; the next tick tries again.
        if acquired:
            _analyze_pending_otlp()


def _analyze_pending_otlp() -> None:
    """Synchronous body of one OTLP backlog analysis tick - groups buffered otlp_pending_points
    rows by (service, metric_name) and runs each group that is due (_due_otlp_groups), with its
    stored history, through the same MetricAnalysisExecutor
    path the Prometheus autonomous flow uses (backend/app/autonomous/execution.py). Bounded by
    OPS_SIGNALS_OTLP_MAX_BACKLOG_PER_CYCLE (whole series at a time) so one large backlog can't make a cycle run
    indefinitely and starve the next one. Runs on a worker thread (see run_scheduler_loop)."""
    session_local = get_session_local()
    with session_local() as db:
        due = _due_otlp_groups(db, datetime.now(timezone.utc))
        if not due:
            return

        started = time.perf_counter()
        processed = 0
        budget = MAX_BACKLOG_PER_CYCLE
        for service, metric_name, count in due:
            # Whole series only, so none is analyzed on a slice of its points; the first always
            # runs, even when it alone is over the budget.
            if processed and count > budget:
                break
            rows = (
                db.query(OtlpPendingPointEntity)
                .filter(OtlpPendingPointEntity.service == service, OtlpPendingPointEntity.metric_name == metric_name)
                .order_by(OtlpPendingPointEntity.timestamp)
                .all()
            )
            _analyze_otlp_group(db, service, metric_name, rows)
            processed += 1
            budget -= count

        OTLP_ANALYSIS_CYCLE_DURATION_SECONDS.set(time.perf_counter() - started)
        OTLP_ANALYSIS_CYCLE_GROUPS_PROCESSED.set(processed)


def _run_metric_usage_check_if_due() -> None:
    session_local = get_session_local()
    with session_local() as db:
        run_scheduled_check_if_due(db)


async def run_scheduler_loop() -> None:
    """Started as a background task from the FastAPI lifespan; cancelled on shutdown."""
    logger.info("Autonomous policy scheduler started (polling every %ss)", POLL_INTERVAL_SECONDS)
    usage_check: asyncio.Task | None = None
    try:
        while True:
            # Reading every dashboard can take a while, so the metric usage check runs alongside
            # the loop instead of holding up policy runs; at most one at a time.
            if usage_check is None or usage_check.done():
                usage_check = asyncio.create_task(asyncio.to_thread(_run_metric_usage_check_if_due))
                usage_check.add_done_callback(_log_usage_check_failure)
            try:
                await asyncio.to_thread(_run_due_policies_once)
            except Exception:
                logger.exception("Autonomous policy scheduler tick failed")
            try:
                await asyncio.to_thread(_run_pending_otlp_analysis_once)
            except Exception:
                logger.exception("OTLP backlog analysis tick failed")
            try:
                await asyncio.to_thread(run_deploy_discovery_if_due)
            except Exception:
                logger.exception("Deploy discovery tick failed")
            try:
                await asyncio.to_thread(run_point_retention_if_due)
            except Exception:
                logger.exception("Stored point cleanup tick failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Autonomous policy scheduler stopped")
        raise


def _log_usage_check_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Metric usage check tick failed", exc_info=task.exception())
