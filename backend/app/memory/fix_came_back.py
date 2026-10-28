"""The fix that didn't stick: a problem back on a service soon after a case there was fixed.

fix_outcomes judges an old fix by looking forward from it ("came back after 3 days"). This looks
back from the new finding or case, so the warning shows where people are working now. Same rule:
the same service, symptoms at least RECURRENCE_SIMILARITY alike, and the new problem within
RECURRENCE_DAYS after the old case was fixed. When several past fixes match, the latest is named.
No AI here; "why might it not have held?" is the optional fix_came_back_why.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.fix_outcomes import (
    RECURRENCE_DAYS,
    RECURRENCE_SIMILARITY,
    FixOutcome,
    _rfc3339,
    _when_fixed,
    fix_outcomes,
)
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.recall_scoring import service_key
from backend.app.memory.schemas import CameBackAfterFix, PastIncidentMatch
from backend.app.memory.vector_names import SYMPTOM_VECTOR
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.memory.availability import unavailable_reason

# Resolution drafts end with "Still open: ..." when the problem stopped but its cause wasn't fixed.
_STILL_OPEN = re.compile(r"\s*still open\s*:\s*", re.IGNORECASE)
_SEARCH_LIMIT = 20


class CaseFixCameBackResponse(BaseModel):
    case_id: int
    available: bool
    reason: str | None = None
    # This case is the problem coming back after an earlier case's fix.
    came_back: CameBackAfterFix | None = None
    # This case's own fix, when it didn't hold (status "came_back"); None otherwise.
    fix_outcome: FixOutcome | None = None


def split_still_open(corrective_action: str) -> tuple[str, str | None]:
    parts = _STILL_OPEN.split(corrective_action.strip(), maxsplit=1)
    fix = parts[0].strip()
    still_open = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return (fix or corrective_action.strip()), still_open


def latest_fix_before(cases: list[OperationalCaseEntity], moment: datetime | None) -> CameBackAfterFix | None:
    """The latest fix among `cases` made within RECURRENCE_DAYS before `moment`."""
    if moment is None:
        return None
    when = _naive(moment)
    fixed = [(fixed_at, case) for case in cases if (fixed_at := _when_fixed(case)) and fixed_at < when <= fixed_at + timedelta(days=RECURRENCE_DAYS)]
    if not fixed:
        return None
    fixed_at, case = max(fixed, key=lambda pair: pair[0])
    fix, still_open = split_still_open(case.corrective_action)
    return CameBackAfterFix(
        case_id=case.id, title=case.case_title, fixed_at=fixed_at, days=(when - fixed_at).days, fix=fix, still_open=still_open,
    )


def came_back_for_finding(finding: FindingEntity, matches: list[PastIncidentMatch], cases: dict[int, OperationalCaseEntity]) -> CameBackAfterFix | None:
    """From a finding's Seen before? matches: same service and alike enough to be the same problem."""
    ids = {
        match.case_id
        for leader in matches
        for match in [leader, *leader.more_like_this]
        if match.same_service and match.similarity_score >= RECURRENCE_SIMILARITY
    }
    return latest_fix_before([cases[case_id] for case_id in ids if case_id in cases], finding.event_start or finding.created_at)


def find_case_fix_came_back(db: Session, store: VectorStore | None, embedder: Embedder | None, case: OperationalCaseEntity) -> CaseFixCameBackResponse:
    """Both directions for one case: is it a problem back after an earlier fix, and did its own fix hold?"""
    if store is None or embedder is None:
        return CaseFixCameBackResponse(case_id=case.id, available=False, reason=unavailable_reason())
    response = CaseFixCameBackResponse(case_id=case.id, available=True)
    key = service_key((case.finding_snapshot or {}).get("service"))
    if key is not None and case.created_at is not None:
        vector = store.get_vector(CaseMemoryIndexer._generate_point_id(case.id), SYMPTOM_VECTOR) if case.memory_status == "indexed" else None
        if vector is None:
            vector = embedder.encode(CaseDocumentBuilder.build_symptom(case))
        created = _naive(case.created_at)
        hits = store.search(
            vector=vector,
            filters={"must": [
                {"key": "service_key", "match": {"value": key}},
                # No lower bound: a case opened long ago can have been fixed recently.
                {"key": "created_at", "range": {"lt": _rfc3339(created)}},
            ]},
            limit=_SEARCH_LIMIT,
            score_threshold=RECURRENCE_SIMILARITY,
            using=SYMPTOM_VECTOR,
        )
        ids = [hit["payload"].get("case_id") for hit in hits if hit["payload"].get("case_id") not in (None, case.id)]
        earlier = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(ids))).scalars().all() if ids else []
        response.came_back = latest_fix_before(list(earlier), case.created_at)
    if _when_fixed(case) is not None:
        outcome = fix_outcomes(db, store, [case])[case.id]
        response.fix_outcome = outcome if outcome.status == "came_back" else None
    return response


def _naive(moment: datetime) -> datetime:
    return moment.replace(tzinfo=None) if moment.tzinfo else moment
