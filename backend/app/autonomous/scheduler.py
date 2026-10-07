"""Recurring execution for saved autonomous policies.

No scheduler infrastructure (APScheduler, Celery, a worker container) exists anywhere in this
repo, and docker-compose only ever runs one backend instance - so this is deliberately a simple
in-process polling loop, not a distributed job queue. It is only correct for a single backend
instance; scaling the backend to multiple replicas would need this revisited (each replica would
poll independently and could double-fire a due policy).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.autonomous.execution import execute_autonomous_plan_once
from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
from backend.app.autonomous.repository import AutonomousPolicyRepository
from backend.app.autonomous.schemas import AnalysisScope, AutonomousRunRequest, ExecutionPolicy, MonitoringSelection
from backend.app.models.db import get_session_local
from backend.app.models.entities import AutonomousPolicyEntity, OtlpPendingPointEntity
from backend.app.otlp.limits import MAX_BACKLOG_PER_CYCLE
from backend.app.otlp.metrics import OTLP_ANALYSIS_CYCLE_DURATION_SECONDS, OTLP_ANALYSIS_CYCLE_GROUPS_PROCESSED
from backend.app.services.prometheus_service import PrometheusQueryService, resolve_prometheus_connection
from backend.app.services.timeseries_routing_service import build_csv_routing_config

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


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
        due = repo.list_due(now=datetime.now(timezone.utc))
        for policy in due:
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


def _analyze_otlp_group(db: Session, service: str, metric_name: str, rows: list[OtlpPendingPointEntity]) -> None:
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
            pd.DataFrame.from_records(records),
            run_metadata={
                "trigger": "otlp_push",
                "service": service,
                "metric_name": metric_name,
                "point_count": len(rows),
            },
            db=db,
        )
        db.query(OtlpPendingPointEntity).filter(OtlpPendingPointEntity.id.in_(row_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        logger.exception("OTLP analysis cycle failed for service=%s metric_name=%s", service, metric_name)
        db.rollback()


def _run_pending_otlp_analysis_once() -> None:
    """Synchronous body of one OTLP backlog analysis tick - groups buffered otlp_pending_points
    rows by (service, metric_name) and runs each group through the same MetricAnalysisExecutor
    path the Prometheus autonomous flow uses (backend/app/autonomous/execution.py). Bounded by
    OPS_SIGNALS_OTLP_MAX_BACKLOG_PER_CYCLE so one large backlog can't make a cycle run
    indefinitely and starve the next one. Runs on a worker thread (see run_scheduler_loop)."""
    session_local = get_session_local()
    with session_local() as db:
        pending = (
            db.query(OtlpPendingPointEntity)
            .order_by(OtlpPendingPointEntity.received_at)
            .limit(MAX_BACKLOG_PER_CYCLE)
            .all()
        )
        if not pending:
            return

        started = time.perf_counter()
        groups: dict[tuple[str, str], list[OtlpPendingPointEntity]] = defaultdict(list)
        for row in pending:
            groups[(row.service, row.metric_name)].append(row)

        for (service, metric_name), rows in groups.items():
            _analyze_otlp_group(db, service, metric_name, rows)

        OTLP_ANALYSIS_CYCLE_DURATION_SECONDS.set(time.perf_counter() - started)
        OTLP_ANALYSIS_CYCLE_GROUPS_PROCESSED.set(len(groups))


async def run_scheduler_loop() -> None:
    """Started as a background task from the FastAPI lifespan; cancelled on shutdown."""
    logger.info("Autonomous policy scheduler started (polling every %ss)", POLL_INTERVAL_SECONDS)
    try:
        while True:
            try:
                await asyncio.to_thread(_run_due_policies_once)
            except Exception:
                logger.exception("Autonomous policy scheduler tick failed")
            try:
                await asyncio.to_thread(_run_pending_otlp_analysis_once)
            except Exception:
                logger.exception("OTLP backlog analysis tick failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Autonomous policy scheduler stopped")
        raise
