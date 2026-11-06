"""Which findings are still active: the rule the Overview page counts by, shared with
GET /api/metrics (services/finding_metrics.py) so both always give the same number."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, OperationalCaseEntity

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


def problem_ends(db: Session, findings: Sequence[FindingEntity]) -> dict[int, datetime]:
    """When each finding's problem ended, keyed by finding id, for problems that are over: the
    problem's newest finding (from whichever run saw it last, even one outside `findings`) says the
    data went on after its last bad reading. Rows are only read: a problem that comes back gets a
    newer, ongoing finding, and is no longer over."""
    problems = sorted({problem for finding in findings if finding.id is not None and (problem := problem_of(finding)) is not None})
    newest: dict[int, tuple[datetime, int, bool | None, datetime | None]] = {}
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
    ended = {problem: event_end for problem, (_, _, ongoing, event_end) in newest.items() if ongoing is False and event_end is not None}
    return {finding.id: ended[problem] for finding in findings if finding.id is not None and (problem := problem_of(finding)) in ended}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
