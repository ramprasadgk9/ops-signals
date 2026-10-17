"""Did a fix hold? And where else was the same fix used?

Cases don't record whether a fix worked, so it is inferred from what happened next: a fix *held*
if no case with the same symptom (symptom vectors at least RECURRENCE_SIMILARITY alike) was opened
on the same service within RECURRENCE_DAYS of the fix. If one was, the problem *came back*. Until
RECURRENCE_DAYS have passed with no recurrence, it is *too early to tell*. The inference is only as
good as detection: a recurrence nobody opened a case for isn't seen.

"Same fix elsewhere" compares resolution vectors (cause and fix, vector_names), so a case shows
the other incidents its cause and fix also resolved - on any service - each with its own outcome.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.recall_scoring import service_key
from backend.app.memory.vector_names import RESOLUTION_VECTOR, SYMPTOM_VECTOR
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import OperationalCaseEntity
from backend.app.memory.availability import unavailable_reason

RECURRENCE_DAYS = 30
# The same symptom, as measured for recurring-problem groups (recurring.GROUP_SIMILARITY["symptom"]).
RECURRENCE_SIMILARITY = 0.80
# The same cause and fix (recurring.GROUP_SIMILARITY["cause"]): 9 of 11 same-cause pairs, no
# different-cause pair, on the calibration set.
SAME_FIX_SIMILARITY = 0.60
MAX_SAME_FIX = 10

FixStatus = Literal["held", "came_back", "too_early", "not_fixed", "unknown"]
RESOLVED_STATES = {"resolved", "closed", "mitigated"}


class FixOutcome(BaseModel):
    status: FixStatus
    label: str
    came_back_case_id: int | None = None
    came_back_after_days: int | None = None


def _when_fixed(case: OperationalCaseEntity) -> datetime | None:
    if case.case_status not in RESOLVED_STATES or not case.corrective_action:
        return None
    moment = case.resolved_at or case.updated_at or case.created_at
    return moment.replace(tzinfo=None) if moment and moment.tzinfo else moment


def fix_outcomes(
    db: Session,
    store: VectorStore,
    cases: list[OperationalCaseEntity],
    *,
    now: datetime | None = None,
) -> dict[int, FixOutcome]:
    """The inferred outcome of each case's fix, by case id."""
    now_naive = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    point_ids = {case.id: CaseMemoryIndexer._generate_point_id(case.id) for case in cases}
    symptoms = store.get_vectors([point_ids[case.id] for case in cases if _when_fixed(case)], SYMPTOM_VECTOR)
    outcomes: dict[int, FixOutcome] = {}
    for case in cases:
        fixed_at = _when_fixed(case)
        if fixed_at is None:
            outcomes[case.id] = FixOutcome(status="not_fixed", label="No fix recorded")
            continue
        vector = symptoms.get(point_ids[case.id])
        key = service_key((case.finding_snapshot or {}).get("service"))
        if vector is None or key is None:
            outcomes[case.id] = FixOutcome(status="unknown", label="Outcome unknown")
            continue
        until = fixed_at + timedelta(days=RECURRENCE_DAYS)
        hits = store.search(
            vector=vector,
            filters={"must": [
                {"key": "service_key", "match": {"value": key}},
                {"key": "created_at", "range": {"gt": _rfc3339(fixed_at), "lte": _rfc3339(until)}},
            ]},
            limit=5,
            score_threshold=RECURRENCE_SIMILARITY,
            using=SYMPTOM_VECTOR,
        )
        later = _first_other(db, hits, case.id)
        if later is not None:
            days = max(((later.created_at.replace(tzinfo=None) if later.created_at.tzinfo else later.created_at) - fixed_at).days, 0)
            outcomes[case.id] = FixOutcome(
                status="came_back", label=f"Came back after {days} {'day' if days == 1 else 'days'}",
                came_back_case_id=later.id, came_back_after_days=days,
            )
        elif now_naive < until:
            outcomes[case.id] = FixOutcome(status="too_early", label="Too early to tell")
        else:
            outcomes[case.id] = FixOutcome(status="held", label=f"Held for {RECURRENCE_DAYS}+ days")
    return outcomes


def _first_other(db: Session, hits: list[dict], case_id: int) -> OperationalCaseEntity | None:
    ids = [hit["payload"].get("case_id") for hit in hits if hit["payload"].get("case_id") not in (None, case_id)]
    if not ids:
        return None
    later = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(ids))).scalars().all()
    return min(later, key=lambda case: case.created_at or datetime.max, default=None)


def _rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class SameFixMatch(BaseModel):
    case_id: int
    title: str
    service: str | None = None
    similarity_score: float
    root_cause_summary: str | None = None
    corrective_action: str | None = None
    rca_verified: bool = False
    outcome: FixOutcome


class SameFixResponse(BaseModel):
    case_id: int
    available: bool
    reason: str | None = None
    outcome: FixOutcome | None = None
    matches: list[SameFixMatch] = Field(default_factory=list)


def find_same_fix(db: Session, store: VectorStore | None, embedder: Embedder | None, case: OperationalCaseEntity) -> SameFixResponse:
    """Other cases resolved by the same cause and fix as `case`, with how each fix turned out."""
    if store is None or embedder is None:
        return SameFixResponse(case_id=case.id, available=False, reason=unavailable_reason())
    resolution = CaseDocumentBuilder.build_resolution(case)
    if not resolution:
        return SameFixResponse(case_id=case.id, available=False, reason="No cause or fix recorded for this case yet.")
    vector = store.get_vector(CaseMemoryIndexer._generate_point_id(case.id), RESOLUTION_VECTOR) if case.memory_status == "indexed" else None
    if vector is None:
        vector = embedder.encode(resolution)
    hits = store.search(vector=vector, limit=MAX_SAME_FIX + 1, score_threshold=SAME_FIX_SIMILARITY, using=RESOLUTION_VECTOR)
    scores = {hit["payload"].get("case_id"): float(hit["score"]) for hit in hits if hit["payload"].get("case_id") != case.id}
    others = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(list(scores)))).scalars().all() if scores else []
    # A case with the same cause but no fix yet (an open case) has a resolution vector too; it
    # isn't "the same fix", so it isn't listed.
    others = [other for other in others if other.corrective_action]
    outcomes = fix_outcomes(db, store, [case, *others])
    others = sorted(others, key=lambda other: -scores.get(other.id, 0.0))[:MAX_SAME_FIX]
    return SameFixResponse(
        case_id=case.id,
        available=True,
        outcome=outcomes[case.id],
        matches=[
            SameFixMatch(
                case_id=other.id,
                title=other.case_title,
                service=(other.finding_snapshot or {}).get("service"),
                similarity_score=round(scores[other.id], 3),
                root_cause_summary=other.root_cause_summary,
                corrective_action=other.corrective_action,
                rca_verified=other.root_cause_verified,
                outcome=outcomes[other.id],
            )
            for other in others
        ],
    )
