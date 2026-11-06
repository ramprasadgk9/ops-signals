"""Which findings are still active: the rule the Overview page counts by, shared with
GET /api/metrics (services/finding_metrics.py) so both always give the same number."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, OperationalCaseEntity, ProblemEventEntity

CLOSED_STATUSES = {"resolved", "verified", "closed", "completed"}
_CHUNK = 500
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def problem_of(finding: FindingEntity) -> int | None:
    """Every run that sees a problem again stores a new finding; they share the first one's id."""
    return finding.problem_id or finding.id


def is_closed(status: str | None) -> bool:
    return (status or "").lower() in CLOSED_STATUSES


def active_findings(db: Session, findings: Sequence[FindingEntity], cases: Sequence[OperationalCaseEntity] | None = None) -> list[FindingEntity]:
    """The findings whose problem is still open: no closed case on any of its findings, or on the
    first one (even when that one is older than `findings`)."""
    if cases is None:
        cases = db.execute(select(OperationalCaseEntity)).scalars().all()
    cases_by_finding_id = {case.finding_id: case for case in cases}

    def closed(finding_id: int | None) -> bool:
        case = cases_by_finding_id.get(finding_id)
        return case is not None and (is_closed(case.case_status) or is_closed(case.outcome_status))

    closed_problems = {problem_of(finding) for finding in findings if closed(finding.id) or closed(problem_of(finding))}
    return [finding for finding in findings if problem_of(finding) not in closed_problems]


# How a problem was found to be over.
SEEN_ENDING = "seen_ending"
LEVEL_BACK = "level_back"


@dataclass(frozen=True)
class ProblemState:
    """Whether a finding's problem is over, and how a level change stands (ops_problem_events)."""

    # When it ended, if it's over.
    ended_at: datetime | None = None
    # SEEN_ENDING: its newest finding's data went on after the last bad reading (data problems,
    # spikes). LEVEL_BACK: a level change's level came back near where it was before the jump.
    how: str | None = None
    # A level change that came partly back: since when, and the level then.
    partly_since: datetime | None = None
    # The jump, from the problem's first level change: when, and the levels around it.
    changed_at: datetime | None = None
    level_before: float | None = None
    level_during: float | None = None
    level_now: float | None = None


def problem_states(db: Session, findings: Sequence[FindingEntity]) -> dict[int, ProblemState]:
    """The state of each finding's problem, keyed by finding id, for problems that are over or
    partly back. Over: a level change's latest event says it came back, or the problem's newest
    finding (from whichever run saw it last, even one outside `findings`) says the data went on after
    its last bad reading. Rows are only read: a problem that comes back gets a newer, ongoing
    finding or a "reopened" event, and is no longer over."""
    problems = sorted({problem for finding in findings if finding.id is not None and (problem := problem_of(finding)) is not None})
    newest: dict[int, tuple[datetime, int, bool | None, datetime | None]] = {}
    latest_event: dict[int, ProblemEventEntity] = {}
    for start in range(0, len(problems), _CHUNK):
        chunk = problems[start : start + _CHUNK]
        rows = db.execute(
            select(FindingEntity.id, FindingEntity.problem_id, FindingEntity.created_at, FindingEntity.ongoing, FindingEntity.event_end).where(
                or_(FindingEntity.id.in_(chunk), FindingEntity.problem_id.in_(chunk))
            )
        ).all()
        for finding_id, problem_id, created_at, ongoing, event_end in rows:
            problem = problem_id or finding_id
            entry = (_utc(created_at) or _EPOCH, finding_id, ongoing, _utc(event_end))
            if problem not in newest or entry[:2] > newest[problem][:2]:
                newest[problem] = entry
        for event in db.execute(select(ProblemEventEntity).where(ProblemEventEntity.problem_id.in_(chunk)).order_by(ProblemEventEntity.id)).scalars():
            latest_event[event.problem_id] = event

    states: dict[int, ProblemState] = {}
    for problem in problems:
        event = latest_event.get(problem)
        levels = (
            {"changed_at": _utc(event.changed_at), "level_before": event.level_before, "level_during": event.level_during, "level_now": event.level_now}
            if event
            else {}
        )
        if event is not None and event.kind == "ended":
            states[problem] = ProblemState(ended_at=_utc(event.at), how=LEVEL_BACK, **levels)
            continue
        partly = {"partly_since": _utc(event.at), **levels} if event is not None and event.kind == "partly_back" else {}
        _, _, ongoing, event_end = newest.get(problem, (None, None, None, None))
        if ongoing is False and event_end is not None:
            states[problem] = ProblemState(ended_at=event_end, how=SEEN_ENDING, **partly)
        elif partly:
            states[problem] = ProblemState(**partly)
    return {finding.id: states[problem] for finding in findings if finding.id is not None and (problem := problem_of(finding)) in states}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
