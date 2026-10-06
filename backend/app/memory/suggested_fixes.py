"""Suggested fixes for a new finding: what fixed this before, and how often it held.

The finding's past look-alikes come from Seen before? (symptom against symptom). Their fixes are
merged where they say the same thing (resolution vectors at least fix_outcomes.SAME_FIX_SIMILARITY
alike, star-shaped like recurring-problem groups), and each merged fix is ranked by how often it
held (fix_outcomes): "Raise the DB pool size - held 3 of 4 times". A draft runbook can be written
from them by the configured LLM; like the RCA draft it is a suggestion, never saved.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.memory.fix_outcomes import SAME_FIX_SIMILARITY, FixOutcome, fix_outcomes
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.schemas import SeenBeforeResponse
from backend.app.memory.vector_names import RESOLUTION_VECTOR
from backend.app.memory.vector_store import VectorStore, cosine_similarity
from backend.app.models.entities import OperationalCaseEntity

MAX_FIXES = 5


class FixSource(BaseModel):
    case_id: int
    title: str
    service: str | None = None
    corrective_action: str
    outcome: FixOutcome


class SuggestedFix(BaseModel):
    fix: str
    root_cause: str | None = None
    # Outcomes over the cases that used this fix; worked/known leave out "too early" and "unknown".
    held: int = 0
    came_back: int = 0
    too_early: int = 0
    label: str
    verified: int = 0
    sources: list[FixSource] = Field(default_factory=list)


class SuggestedFixesResponse(BaseModel):
    finding_id: int
    available: bool
    reason: str | None = None
    based_on_cases: int = 0
    fixes: list[SuggestedFix] = Field(default_factory=list)


class RunbookDraft(BaseModel):
    """A suggested-only draft; never written anywhere."""

    available: bool
    draft: str | None = None
    reason: str | None = None
    based_on_cases: list[int] = Field(default_factory=list)


def suggest_fixes(db: Session, store: VectorStore | None, seen_before: SeenBeforeResponse) -> SuggestedFixesResponse:
    response = SuggestedFixesResponse(finding_id=seen_before.finding_id, available=False)
    if store is None or not seen_before.available:
        response.reason = seen_before.reason or "Operational memory is not enabled."
        return response
    # Same-service matches only: a fix from another service is shown under Seen before?, but
    # isn't suggested as the fix for this one.
    ids = [
        match.case_id
        for leader in seen_before.matches if leader.same_service or not seen_before.service
        for match in [leader, *leader.more_like_this]
        if match.corrective_action
    ]
    cases = {case.id: case for case in db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(ids))).scalars()} if ids else {}
    ordered = [cases[case_id] for case_id in dict.fromkeys(ids) if case_id in cases]
    response.available = True
    response.based_on_cases = len(ordered)
    if not ordered:
        response.reason = "None of the past cases like this one on this service recorded a fix."
        return response

    point_ids = {case.id: CaseMemoryIndexer._generate_point_id(case.id) for case in ordered}
    vectors = store.get_vectors(list(point_ids.values()), RESOLUTION_VECTOR)
    outcomes = fix_outcomes(db, store, ordered)
    groups = _group_by_fix(ordered, {case.id: vectors.get(point_ids[case.id]) for case in ordered})
    fixes = [_suggested(group, outcomes) for group in groups]
    fixes.sort(key=lambda fix: (-fix.held, fix.came_back, -fix.verified, -len(fix.sources)))
    response.fixes = fixes[:MAX_FIXES]
    return response


def _group_by_fix(cases: list[OperationalCaseEntity], vectors: dict[int, list[float] | None]) -> list[list[OperationalCaseEntity]]:
    """Cases in recall order; each joins the first group whose first case's fix it matches."""
    groups: list[list[OperationalCaseEntity]] = []
    for case in cases:
        vector = vectors.get(case.id)
        for group in groups:
            lead = vectors.get(group[0].id)
            if vector and lead and cosine_similarity(vector, lead) >= SAME_FIX_SIMILARITY:
                group.append(case)
                break
        else:
            groups.append([case])
    return groups


def _suggested(group: list[OperationalCaseEntity], outcomes: dict[int, FixOutcome]) -> SuggestedFix:
    statuses = [outcomes[case.id].status for case in group]
    held, came_back, too_early = statuses.count("held"), statuses.count("came_back"), statuses.count("too_early")
    known = held + came_back
    # Worded from the case whose fix held, then a verified one, then the closest match.
    lead = min(group, key=lambda case: (outcomes[case.id].status != "held", not case.root_cause_verified))
    times = 'time' if known == 1 else 'times'
    if held:
        label = f"Held {held} of {known} {times}"
    elif known:
        label = f"Came back {came_back} of {known} {times}"
    elif too_early:
        label = "Too early to tell"
    else:
        label = "Outcome unknown"
    return SuggestedFix(
        fix=lead.corrective_action,
        root_cause=lead.root_cause_summary,
        held=held,
        came_back=came_back,
        too_early=too_early,
        label=label,
        verified=sum(1 for case in group if case.root_cause_verified),
        sources=[
            FixSource(
                case_id=case.id, title=case.case_title, service=(case.finding_snapshot or {}).get("service"),
                corrective_action=case.corrective_action, outcome=outcomes[case.id],
            )
            for case in group
        ],
    )


_RUNBOOK_INSTRUCTION = (
    "Write a short runbook for an on-call engineer facing a new operational finding, as 3-7 numbered "
    "steps. Use ONLY the past fixes given: prefer fixes that held, mention ones that came back only as "
    "a caution, and cite the case numbers each step comes from like (case #12). Start with how to "
    "confirm the cause before changing anything. Do not invent commands, values or causes that are not "
    "in the evidence. This is a draft for a person to check."
)


def draft_runbook(finding_title: str, suggestions: SuggestedFixesResponse, ai_services: OptionalAIServices | None) -> RunbookDraft:
    if ai_services is None:
        return RunbookDraft(available=False, reason="AI assistance is not configured.")
    if not suggestions.fixes:
        return RunbookDraft(available=False, reason=suggestions.reason or "No past fixes to draft a runbook from.")
    lines = [f"New finding: {finding_title}", ""]
    for number, fix in enumerate(suggestions.fixes, start=1):
        lines.append(f"Fix {number}: {fix.fix} ({fix.label})")
        if fix.root_cause:
            lines.append(f"  cause: {fix.root_cause}")
        for source in fix.sources:
            lines.append(f"  case #{source.case_id}: {source.title} - {source.outcome.label}")
    draft = synthesize_narrative(ai_services, instruction=_RUNBOOK_INSTRUCTION, evidence_text="\n".join(lines), max_tokens=400)
    case_ids = [source.case_id for fix in suggestions.fixes for source in fix.sources]
    if not draft:
        return RunbookDraft(available=False, reason="AI draft generation failed.", based_on_cases=case_ids)
    return RunbookDraft(available=True, draft=draft, based_on_cases=case_ids)
