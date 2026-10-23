"""Which findings are still active: the rule the Overview page counts by, shared with
GET /api/metrics (services/finding_metrics.py) so both always give the same number."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, OperationalCaseEntity

CLOSED_STATUSES = {"resolved", "verified", "closed", "completed"}


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
