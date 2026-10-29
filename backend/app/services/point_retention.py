"""Deletes stored metric points older than the retention period.

Findings keep their own numbers and wording, so only the chart behind an old finding goes. Points
behind a finding someone opened a case for are kept at any age: they are the incident's record, and
few findings become cases. Runs from the scheduler loop about once an hour, in batches so no
delete holds locks for long. Two backends running it at once delete the same rows; that's harmless.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, false, not_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.behavior_intelligence.schemas import run_ids_of
from backend.app.models.entities import (
    AnalysisRunEntity,
    BehaviorFindingEntity,
    FindingEntity,
    NormalizedPoint,
    OperationalCaseEntity,
)

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30
CHECK_INTERVAL_SECONDS = 3600
BATCH_SIZE = 5_000
# A first cleanup after an upgrade can face millions of rows; the rest waits for the next tick so
# the scheduler loop isn't held up.
MAX_DELETED_PER_RUN = 200_000

_last_started: float | None = None


def retention_days() -> int:
    """OPS_SIGNALS_POINT_RETENTION_DAYS; 0 keeps every point."""
    return max(0, int(os.getenv("OPS_SIGNALS_POINT_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))))


def points_deleted(end_time: datetime | str, *, now: datetime | None = None) -> bool:
    """True when a run ended before the retention period, so its points are gone unless a case
    kept them. Takes text too: raw SQL on SQLite returns timestamps as strings."""
    days = retention_days()
    if days <= 0:
        return False
    if isinstance(end_time, str):
        end_time = datetime.fromisoformat(end_time)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    return end_time < (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _kept_for_cases(db: Session) -> ColumnElement[bool]:
    """Points behind a finding or behavior that has a case: the run's own points, and for runs
    stored by series (run_points.py) the series' points in the run's window."""
    run_ids = set(db.execute(select(OperationalCaseEntity.analysis_run_id)).scalars())
    run_ids |= set(
        db.execute(
            select(FindingEntity.analysis_run_id).join(OperationalCaseEntity, OperationalCaseEntity.finding_id == FindingEntity.id)
        ).scalars()
    )
    # A pattern from a scheduled analysis spans one run per metric; keep them all.
    for run_id, correlation in db.execute(
        select(BehaviorFindingEntity.analysis_run_id, BehaviorFindingEntity.correlation_json).join(
            OperationalCaseEntity, OperationalCaseEntity.behavior_finding_id == BehaviorFindingEntity.id
        )
    ).all():
        run_ids |= set(run_ids_of(run_id, correlation))
    run_ids.discard(None)
    run_ids.discard("")
    if not run_ids:
        return false()
    # IS NOT NULL first: a NULL comparison would make NOT(...) NULL and keep the point forever.
    kept = [and_(NormalizedPoint.analysis_run_id.is_not(None), NormalizedPoint.analysis_run_id.in_(run_ids))]
    series_runs = db.execute(
        select(AnalysisRunEntity.series_key, AnalysisRunEntity.start_time, AnalysisRunEntity.end_time).where(
            AnalysisRunEntity.id.in_(run_ids), AnalysisRunEntity.series_key.is_not(None)
        )
    ).all()
    for key, start, end in series_runs:
        kept.append(
            and_(
                NormalizedPoint.series_key.is_not(None),
                NormalizedPoint.series_key == key,
                NormalizedPoint.timestamp >= start,
                NormalizedPoint.timestamp <= end,
            )
        )
    return or_(*kept)


def delete_old_points(
    db: Session,
    *,
    days: int,
    now: datetime | None = None,
    batch_size: int = BATCH_SIZE,
    max_deleted: int = MAX_DELETED_PER_RUN,
) -> tuple[int, bool]:
    """Deletes up to `max_deleted` points older than `days`. Returns (deleted, more_left)."""
    if days <= 0:
        return 0, False
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    old = and_(NormalizedPoint.timestamp < cutoff, not_(_kept_for_cases(db)))
    deleted = 0
    while deleted < max_deleted:
        ids = db.execute(select(NormalizedPoint.id).where(old).limit(min(batch_size, max_deleted - deleted))).scalars().all()
        if not ids:
            return deleted, False
        db.execute(delete(NormalizedPoint).where(NormalizedPoint.id.in_(ids)).execution_options(synchronize_session=False))
        db.commit()
        deleted += len(ids)
    return deleted, True


def run_if_due() -> None:
    """Called on every scheduler tick; runs about once an hour, or on the next tick while a large
    backlog is left."""
    global _last_started
    days = retention_days()
    if days <= 0:
        return
    clock = time.monotonic()
    if _last_started is not None and clock - _last_started < CHECK_INTERVAL_SECONDS:
        return
    _last_started = clock

    from backend.app.models.db import get_session_local

    with get_session_local()() as db:
        deleted, more_left = delete_old_points(db, days=days)
    if deleted:
        logger.info("Deleted %s stored metric points older than %s days", deleted, days)
    if more_left:
        _last_started = None
