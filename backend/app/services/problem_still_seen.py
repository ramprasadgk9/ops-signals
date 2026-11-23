"""Whether a case's problem is still being found: the Resolution tab warns before it's resolved.

Resolving a case while its problem goes on hides the problem from Overview, the handoff and the
active-findings metric, and saves the fix as one that worked. Only rows already stored are read;
nothing here blocks or changes a save.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.services.active_findings import problem_of, problem_states


@dataclass(frozen=True)
class StillSeen:
    # The newest finding of the problem and when its run saved it.
    finding_id: int
    seen_at: datetime


def problem_still_seen(db: Session, case: OperationalCaseEntity) -> StillSeen | None:
    """The problem's newest finding when a run found it again after the case was opened and it was
    still going at the end of that run's data. None when it wasn't seen since (a one-off analysis,
    or runs that stopped finding it), when it's over, or for a case without a finding (imported,
    behavior pattern)."""
    if case.finding_id is None:
        return None
    finding = db.get(FindingEntity, case.finding_id)
    if finding is None:
        return None
    problem = problem_of(finding)
    newest = db.execute(
        select(FindingEntity)
        .where(or_(FindingEntity.id == problem, FindingEntity.problem_id == problem))
        .order_by(FindingEntity.created_at.desc(), FindingEntity.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if newest is None or newest.created_at is None or case.created_at is None:
        return None
    if _utc(newest.created_at) <= _utc(case.created_at) or newest.ongoing is False:
        return None
    state = problem_states(db, [newest]).get(newest.id)
    if state is not None and state.ended_at is not None:
        return None
    return StillSeen(finding_id=newest.id, seen_at=_utc(newest.created_at))


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
