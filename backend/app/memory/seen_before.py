"""'Seen before?' for a finding: past cases that look like it, without opening a case first.

Similar Cases used to be reachable only from Case Details, so a new finding never showed its history
until someone filed a case for it. This runs the same kind of search alert recall does - the
finding's own words against case documents - and ranks same-service matches first.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.embedder import Embedder
from backend.app.memory.schemas import PastIncidentMatch, SeenBeforeResponse
from backend.app.memory.similarity_service import (
    POSSIBLE_MATCH_SCORE,
    SimilarityService,
    match_strength,
    same_metric_or_imported,
)
from backend.app.models.entities import FindingEntity, OperationalCaseEntity

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
            reason="Operational memory is not enabled, so past cases can't be searched.",
            service=finding.service,
        )

    vector = embedder.encode(finding_query_text(finding))
    results = similarity.vector_store.search(
        vector=vector,
        filters={"must": [same_metric_or_imported(finding.metric_name)]},
        limit=MAX_MATCHES * 3,
        score_threshold=POSSIBLE_MATCH_SCORE,
    )
    case_ids = [result["payload"].get("case_id") for result in results if result["payload"].get("case_id")]
    cases = {
        case.id: case
        for case in db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(case_ids))).scalars()
    } if case_ids else {}

    matches: list[PastIncidentMatch] = []
    for result in results:
        case = cases.get(result["payload"].get("case_id"))
        # The finding's own case would always be the top hit; it isn't "before".
        if case is None or case.finding_id == finding.id:
            continue
        snapshot = case.finding_snapshot or {}
        service = snapshot.get("service")
        matches.append(
            PastIncidentMatch(
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
                reference=f"/cases/{case.id}",
            )
        )
    # Same service first, then strength, then score: a possible match on this service is more
    # useful than a strong-looking one elsewhere.
    matches.sort(key=lambda match: (not match.same_service, match.strength != "strong", -match.similarity_score))
    return SeenBeforeResponse(
        finding_id=finding.id,
        available=True,
        service=finding.service,
        matches=matches[:MAX_MATCHES],
    )
