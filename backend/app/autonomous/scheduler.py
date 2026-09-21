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
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.autonomous.execution import execute_autonomous_plan_once
from backend.app.autonomous.repository import AutonomousPolicyRepository
from backend.app.autonomous.schemas import AnalysisScope, AutonomousRunRequest, ExecutionPolicy, MonitoringSelection
from backend.app.config import get_prometheus_config
from backend.app.models.db import get_session_local
from backend.app.models.entities import AutonomousPolicyEntity
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


def _build_run_request(policy: AutonomousPolicyEntity) -> AutonomousRunRequest:
    return AutonomousRunRequest(
        datasource=policy.datasource,
        backend=policy.backend,
        scope=AnalysisScope(**policy.scope_json),
        monitoring_selection=MonitoringSelection(**policy.monitoring_categories_json),
        execution=ExecutionPolicy(**policy.execution_policy_json),
        dry_run=False,
    )


def _run_one_policy(db: Session, repo: AutonomousPolicyRepository, policy: AutonomousPolicyEntity) -> None:
    # Imported here, not at module load time, to avoid a circular import: backend.app.api.autonomous
    # imports from this package's repository/schemas modules already.
    from backend.app.api.autonomous import preview_autonomous_plan

    config = get_prometheus_config()
    prometheus = PrometheusQueryService(config)
    request = _build_run_request(policy)
    status = "failed"
    try:
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


async def run_scheduler_loop() -> None:
    """Started as a background task from the FastAPI lifespan; cancelled on shutdown."""
    logger.info("Autonomous policy scheduler started (polling every %ss)", POLL_INTERVAL_SECONDS)
    try:
        while True:
            try:
                await asyncio.to_thread(_run_due_policies_once)
            except Exception:
                logger.exception("Autonomous policy scheduler tick failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Autonomous policy scheduler stopped")
        raise
