"""One case per problem. Every run that sees a problem again stores a new finding, linked to the
first one by problem_id (intelligence/storage/postgres_store.py); a case opened on any of those
findings is the problem's case, so a later finding of it opens that case instead of a second one."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.services.active_findings import problem_of


def problems_of(db: Session, finding_ids: Iterable[int]) -> dict[int, int]:
    """Finding id -> its problem (the problem's first finding id). Unknown ids are left out."""
    ids = list({finding_id for finding_id in finding_ids if finding_id is not None})
    if not ids:
        return {}
    rows = db.execute(select(FindingEntity.id, FindingEntity.problem_id).where(FindingEntity.id.in_(ids))).all()
    return {finding_id: problem_id or finding_id for finding_id, problem_id in rows}


def cases_of_problems(db: Session, problems: Iterable[int]) -> dict[int, OperationalCaseEntity]:
    """Problem -> its case: the first one opened on any of its findings (more than one only for
    cases opened before this rule)."""
    wanted = list({problem for problem in problems if problem is not None})
    if not wanted:
        return {}
    rows = db.execute(
        select(OperationalCaseEntity, FindingEntity.id, FindingEntity.problem_id)
        .join(FindingEntity, OperationalCaseEntity.finding_id == FindingEntity.id)
        .where(or_(FindingEntity.id.in_(wanted), FindingEntity.problem_id.in_(wanted)))
        .order_by(OperationalCaseEntity.id)
    ).all()
    found: dict[int, OperationalCaseEntity] = {}
    for case, finding_id, problem_id in rows:
        found.setdefault(problem_id or finding_id, case)
    return found


def case_for_finding_problem(db: Session, finding: FindingEntity, *, lock: bool = False) -> OperationalCaseEntity | None:
    """The case of `finding`'s problem, on this finding or any other run's finding of it.

    lock=True holds the problem's first finding row until the transaction ends, so two requests
    opening a case on different findings of one problem can't both find none and both insert."""
    problem = problem_of(finding)
    if lock and problem is not None:
        db.execute(select(FindingEntity.id).where(FindingEntity.id == problem).with_for_update())
    return cases_of_problems(db, [problem]).get(problem)
