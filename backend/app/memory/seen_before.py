"""'Seen before?' for a finding: past cases that look like it, without opening a case first.

Similar Cases used to be reachable only from Case Details, so a new finding never showed its history
until someone filed a case for it. This runs the same kind of search alert recall does - the
finding's own words against case documents - and lists same-service matches first, each group in
the shared recall ranking (recall_scoring).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.diversity import collapse_near_copies
from backend.app.memory.embedder import Embedder
from backend.app.memory.fix_came_back import came_back_for_finding
from backend.app.memory.match_investigations import latest_investigations
from backend.app.memory.novelty import assess_novelty
from backend.app.memory.recall_scoring import RecallBoost
from backend.app.memory.schemas import PastIncidentMatch, SeenBeforeResponse
from backend.app.memory.similarity_service import (
    POSSIBLE_MATCH_SCORE,
    SimilarityService,
    match_strength,
    same_metric_or_imported,
)
from backend.app.memory.vector_names import SYMPTOM_VECTOR
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.memory.availability import unavailable_reason
from backend.app.services.case_status import derive_case_status

MAX_MATCHES = 8


def finding_query_text(finding: FindingEntity) -> str:
    return f"{finding.service or ''} {finding.metric_name}: {finding.title}. {finding.ai_summary or finding.summary or ''}".strip()


def find_seen_before(
    db: Session,
    finding: FindingEntity,
    similarity: SimilarityService | None,
    embedder: Embedder | None,
) -> SeenBeforeResponse:
    if similarity is None or embedder is None:
        return SeenBeforeResponse(
            finding_id=finding.id,
            available=False,
            reason=unavailable_reason("past cases can't be searched"),
            service=finding.service,
        )

    query_text = finding_query_text(finding)
    vector = embedder.encode(query_text)
    # Symptom against symptom: the finding says what was seen, so it is compared with what past
    # cases saw, not with their causes and fixes (vector_names).
    results = similarity.vector_store.search(
        vector=vector,
        filters={"must": [same_metric_or_imported(finding.metric_name)]},
        limit=MAX_MATCHES * 3,
        score_threshold=POSSIBLE_MATCH_SCORE,
        text=query_text,
        boost=RecallBoost(service=finding.service),
        using=SYMPTOM_VECTOR,
    )
    case_ids = [result["payload"].get("case_id") for result in results if result["payload"].get("case_id")]
    cases = {
        case.id: case
        for case in db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(case_ids))).scalars()
    } if case_ids else {}
    investigations = latest_investigations(db, list(cases.values()))

    def to_match(result: dict) -> PastIncidentMatch | None:
        case = cases.get(result["payload"].get("case_id"))
        # The finding's own case would always be the top hit; it isn't "before".
        if case is None or case.finding_id == finding.id:
            return None
        snapshot = case.finding_snapshot or {}
        service = snapshot.get("service")
        investigation = investigations.get(case.id)
        return PastIncidentMatch(
            case_id=case.id,
            title=case.case_title,
            similarity_score=float(result["score"]),
            strength=match_strength(float(result["score"])),
            same_service=bool(service and finding.service and service.lower() == finding.service.lower()),
            service=service,
            metric_name=snapshot.get("metric_name"),
            origin="imported" if case.is_imported else "detected",
            source=case.source,
            source_id=case.source_id,
            source_url=case.source_url,
            root_cause_summary=case.root_cause_summary,
            corrective_action=case.corrective_action,
            outcome_summary=case.outcome_summary,
            resolved_at=case.resolved_at,
            case_status=derive_case_status(case)[0],
            rca_verified=bool(case.root_cause_verified),
            opened_at=case.created_at,
            investigation_ending=investigation.ending if investigation else None,
            investigation_summary=investigation.summary if investigation else None,
            reference=f"/cases/{case.id}",
        )

    matches: list[PastIncidentMatch] = []
    every_match: list[PastIncidentMatch] = []
    for leader, copies in collapse_near_copies(results):
        match = to_match(leader)
        folded = [copy for copy in map(to_match, copies) if copy is not None]
        if match is None:
            # The finding's own case led the group; its near-copies are still past cases.
            if not folded:
                continue
            match, folded = folded[0], folded[1:]
        match.more_like_this = folded
        matches.append(match)
        every_match.extend([match, *folded])
    # Same service first, so other services can't crowd it out of MAX_MATCHES; within each group the
    # recall ranking is kept (a stable sort). A possible match on this service is more useful than a
    # strong-looking one elsewhere.
    matches.sort(key=lambda match: not match.same_service)
    return SeenBeforeResponse(
        finding_id=finding.id,
        available=True,
        service=finding.service,
        matches=matches[:MAX_MATCHES],
        # Counted over every match - folded near-copies and those past MAX_MATCHES included - so
        # "recurring" sees the whole history.
        novelty=assess_novelty(every_match, finding.service),
        came_back=came_back_for_finding(finding, matches, cases),
    )
