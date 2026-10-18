"""Recurring problems: past cases grouped into the problems that keep coming back.

A single incident gets fixed; a problem that happened seven times in ninety days needs a lasting
fix. This groups recent cases by how alike they are, using Qdrant's distance matrix (each case's
closest neighbours among the cases in the window), so Operational Memory can show "checkout-api
latency, 6 times in 90 days" with the causes and fixes found each time.

Grouping is star-shaped, not chained: each group has a central case (the one with the most close
neighbours), and every other case in the group is at least GROUP_SIMILARITY like that central case.
A chain of loose look-alikes (A like B, B like C, C nothing like A) can't merge into one group.

Two ways to group (vector_names):
- by symptom (the default): what was seen - service, metric, what happened. Different causes of the
  same symptom land in one group, which is the point: the causes listed show which keeps recurring.
  Symptom text has the same shape for detected cases and imported postmortems, so a postmortem
  groups with the detected cases of the same problem.
- by cause: the root cause and fix, so one cause that keeps coming back shows up as one group even
  across services and symptoms. Only cases with a recorded cause or fix take part.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.vector_names import RESOLUTION_VECTOR, SYMPTOM_VECTOR
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import OperationalCaseEntity
from backend.app.memory.availability import unavailable_reason

logger = logging.getLogger(__name__)

GroupBy = Literal["symptom", "cause"]

# Every case in a group is at least this similar to the group's central case, per grouping.
# Measured: the same symptom scores 0.77-0.93 on symptom vectors, unrelated symptoms at most 0.46
# (0.84 for two cert-expiry 5xx incidents, rightly). Cause-and-fix text is noisier - the same cause
# scores 0.41-0.89, different causes at most 0.49 - so 0.60 keeps groups clean and misses some
# differently worded fixes.
GROUP_SIMILARITY: dict[str, float] = {"symptom": 0.80, "cause": 0.60}
_GROUP_VECTOR = {"symptom": SYMPTOM_VECTOR, "cause": RESOLUTION_VECTOR}
# Cases compared, and neighbours kept per case, in one distance-matrix call.
MAX_CASES = 500
NEIGHBOURS = 25
MAX_PROBLEMS = 10
# Every case's cause is returned (the UI shows the first few); this only bounds a huge group.
MAX_CAUSES = 50


class RecurringCase(BaseModel):
    case_id: int
    title: str
    service: str | None = None
    created_at: datetime | None = None
    origin: str = "detected"
    case_status: str
    rca_verified: bool = False
    similarity_to_central: float


class RecurringCause(BaseModel):
    case_id: int
    root_cause: str
    fix: str | None = None
    verified: bool = False


class RecurringProblem(BaseModel):
    name: str
    # "ai" when an LLM named the group from its cases; otherwise the central case's title.
    named_by: str = "central_case"
    central_case_id: int
    occurrences: int
    services: list[str] = Field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    verified_root_causes: int = 0
    open_cases: int = 0
    causes: list[RecurringCause] = Field(default_factory=list)
    cases: list[RecurringCase] = Field(default_factory=list)


class RecurringProblemsResponse(BaseModel):
    available: bool
    reason: str | None = None
    window_days: int
    min_occurrences: int
    group_by: GroupBy = "symptom"
    group_similarity: float = GROUP_SIMILARITY["symptom"]
    cases_considered: int = 0
    # True when the window held more than MAX_CASES indexed cases and only a sample was compared.
    sampled: bool = False
    problems: list[RecurringProblem] = Field(default_factory=list)


def find_recurring_problems(
    db: Session,
    store: VectorStore | None,
    *,
    days: int = 90,
    min_occurrences: int = 3,
    group_by: GroupBy = "symptom",
    ai_services: OptionalAIServices | None = None,
    now: datetime | None = None,
) -> RecurringProblemsResponse:
    threshold = GROUP_SIMILARITY[group_by]
    response = RecurringProblemsResponse(
        available=False, window_days=days, min_occurrences=min_occurrences, group_by=group_by, group_similarity=threshold,
    )
    if store is None:
        response.reason = unavailable_reason("past cases can't be compared")
        return response

    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    since_naive = since.astimezone(timezone.utc).replace(tzinfo=None)
    cases = db.execute(
        select(OperationalCaseEntity).where(
            OperationalCaseEntity.memory_status.in_(("indexed", "stale")),
            OperationalCaseEntity.created_at >= since_naive,
        )
    ).scalars().all()
    if group_by == "cause":
        cases = [case for case in cases if case.root_cause_summary or case.corrective_action]
    by_point = {CaseMemoryIndexer._generate_point_id(case.id): case for case in cases}
    response.cases_considered = len(cases)
    response.sampled = len(cases) > MAX_CASES
    if len(cases) < min_occurrences:
        response.available = True
        return response

    try:
        pairs = store.similarity_pairs(
            filters={"must": [{"key": "created_at", "range": {"gte": since.strftime("%Y-%m-%dT%H:%M:%SZ")}}]},
            sample=MAX_CASES,
            neighbours=NEIGHBOURS,
            using=_GROUP_VECTOR[group_by],
        )
    except Exception as e:
        logger.warning(f"Recurring problems: comparing cases failed: {e}")
        response.reason = "Past cases could not be compared."
        return response

    neighbours: dict[str, dict[str, float]] = defaultdict(dict)
    for a, b, score in pairs:
        if score >= threshold and a in by_point and b in by_point and a != b:
            neighbours[a][b] = max(score, neighbours[a].get(b, 0.0))
            neighbours[b][a] = max(score, neighbours[b].get(a, 0.0))

    problems = [
        _problem(by_point[central], [(by_point[point], score) for point, score in members])
        for central, members in _star_groups(neighbours, by_point, min_occurrences)
    ]
    problems.sort(key=lambda problem: (-problem.occurrences, -(problem.last_seen or since_naive).timestamp()))
    response.problems = problems[:MAX_PROBLEMS]
    _name_with_ai(response.problems, ai_services)
    response.available = True
    return response


def _star_groups(neighbours: dict[str, dict[str, float]], by_point: dict, min_size: int) -> list[tuple[str, list[tuple[str, float]]]]:
    """Most-connected case first: it and its unassigned close neighbours form a group, if that is
    big enough. A case too small to centre a group can still join a later one."""
    def latest(point: str) -> float:
        created = by_point[point].created_at
        return created.timestamp() if created else 0.0

    order = sorted(neighbours, key=lambda point: (-len(neighbours[point]), -latest(point)))
    assigned: set[str] = set()
    groups = []
    for central in order:
        if central in assigned:
            continue
        members = [(point, score) for point, score in neighbours[central].items() if point not in assigned]
        if len(members) + 1 < min_size:
            continue
        assigned.add(central)
        assigned.update(point for point, _ in members)
        groups.append((central, [(central, 1.0), *members]))
    return groups


def _problem(central: OperationalCaseEntity, members: list[tuple[OperationalCaseEntity, float]]) -> RecurringProblem:
    def when(case: OperationalCaseEntity) -> float:
        return case.created_at.timestamp() if case.created_at else 0.0

    members = sorted(members, key=lambda member: -when(member[0]))
    cases = [case for case, _ in members]
    services = sorted({service for case in cases if (service := (case.finding_snapshot or {}).get("service"))})
    dates = [case.created_at for case in cases if case.created_at]
    # Verified causes first, then the most recent.
    with_cause = sorted((case for case in cases if case.root_cause_summary), key=lambda case: (not case.root_cause_verified, -when(case)))
    return RecurringProblem(
        name=central.case_title,
        central_case_id=central.id,
        occurrences=len(cases),
        services=services,
        first_seen=min(dates) if dates else None,
        last_seen=max(dates) if dates else None,
        verified_root_causes=sum(1 for case in cases if case.root_cause_verified),
        open_cases=sum(1 for case in cases if case.case_status not in ("resolved", "closed")),
        causes=[
            RecurringCause(case_id=case.id, root_cause=case.root_cause_summary, fix=case.corrective_action, verified=case.root_cause_verified)
            for case in with_cause[:MAX_CAUSES]
        ],
        cases=[
            RecurringCase(
                case_id=case.id,
                title=case.case_title,
                service=(case.finding_snapshot or {}).get("service"),
                created_at=case.created_at,
                origin="imported" if case.is_imported else "detected",
                case_status=case.case_status,
                rca_verified=case.root_cause_verified,
                similarity_to_central=round(score, 3),
            )
            for case, score in members
        ],
    )


_NAME_LINE = re.compile(r"^\s*(\d+)\s*[.:)\-]\s*(.+?)\s*$")
_NAMING_INSTRUCTION = (
    "You name groups of operational incidents. Each numbered group lists incidents that look alike. "
    "For each group, give a short name (at most 8 words) for the problem they share, using only the "
    "titles and causes given - name the symptom and service, and the cause only if most incidents "
    "share it. Reply with exactly one line per group, formatted '<number>. <name>', and nothing else."
)


def _name_with_ai(problems: list[RecurringProblem], ai_services: OptionalAIServices | None) -> None:
    """One LLM call names every group; any group it doesn't name keeps its central case's title."""
    if not problems or ai_services is None:
        return
    evidence = []
    for number, problem in enumerate(problems, start=1):
        evidence.append(f"Group {number}:")
        evidence.extend(f"- {case.title}" for case in problem.cases[:6])
        evidence.extend(f"  cause: {cause.root_cause}" for cause in problem.causes[:3])
    reply = synthesize_narrative(ai_services, instruction=_NAMING_INSTRUCTION, evidence_text="\n".join(evidence), max_tokens=40 * len(problems), min_words=1)
    for line in (reply or "").splitlines():
        match = _NAME_LINE.match(line)
        if not match:
            continue
        index = int(match.group(1)) - 1
        name = match.group(2).strip().strip('"').strip()
        if 0 <= index < len(problems) and name and len(name) <= 80:
            problems[index].name = name
            problems[index].named_by = "ai"
