"""The latest guided investigation behind each past-case match, for the match's one-line outcome.

A guided investigation (backend/app/investigation/) belongs to a case through its case_id, or,
when it ran before the case existed, through the case's finding.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import InvestigationEntity, OperationalCaseEntity


def latest_investigations(db: Session, cases: list[OperationalCaseEntity]) -> dict[int, InvestigationEntity]:
    """Case id -> its most recent investigation; cases without one are left out."""
    case_ids = [case.id for case in cases]
    finding_ids = [case.finding_id for case in cases if case.finding_id is not None]
    if not case_ids:
        return {}
    clauses = [InvestigationEntity.case_id.in_(case_ids)]
    if finding_ids:
        clauses.append(InvestigationEntity.finding_id.in_(finding_ids))
    rows = db.execute(select(InvestigationEntity).where(or_(*clauses)).order_by(InvestigationEntity.id)).scalars().all()
    by_case = {case.id: case for case in cases}
    by_finding = {case.finding_id: case.id for case in cases if case.finding_id is not None}
    latest: dict[int, InvestigationEntity] = {}
    for row in rows:
        case_id = row.case_id if row.case_id in by_case else by_finding.get(row.finding_id)
        if case_id is not None:
            latest[case_id] = row  # ordered by id, so the last one wins
    return latest
