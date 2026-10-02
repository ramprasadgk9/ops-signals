"""Alert-context lookup, shared by `GET /api/alert-context` and the alert enrichment receiver."""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.memory.embedder import Embedder
from backend.app.memory.schemas import (
    AlertContextHistory,
    AlertContextOutcome,
    AlertContextRawActivity,
    AlertContextResponse,
    AlertContextSimilarCase,
)
from backend.app.memory.similarity_service import SimilarityService, same_metric_or_imported
from backend.app.models.entities import AnalyzerLearningOutcomeEntity, BehaviorFindingEntity, FindingEntity, OperationalCaseEntity

logger = logging.getLogger(__name__)


def build_alert_context(
    db: Session,
    metric_name: str,
    service: str | None = None,
    message: str | None = None,
    similarity: SimilarityService | None = None,
    embedder: Embedder | None = None,
    assistant: OperationalIntelligenceAssistant | None = None,
) -> AlertContextResponse:
    """Decision-support lookup for an incoming alert, meant for an external
    alert manager to call before firing: has this service/metric fired before,
    was it real, and what similar cases (if any) were resolved.

    Works from Postgres learning outcomes alone (exact service+metric match);
    if `message` is given and operational memory is enabled, also runs a
    free-text semantic search over past cases - no prior case_id required.
    """
    outcome_query = select(AnalyzerLearningOutcomeEntity).where(
        AnalyzerLearningOutcomeEntity.metric_name == metric_name
    )
    if service:
        outcome_query = outcome_query.where(AnalyzerLearningOutcomeEntity.service_id == service)
    outcome_query = outcome_query.order_by(AnalyzerLearningOutcomeEntity.created_at.desc()).limit(20)
    outcomes = db.execute(outcome_query).scalars().all()

    status_counts = Counter(outcome.outcome_status for outcome in outcomes)
    confirmed = status_counts.get("confirmed", 0)
    rejected = status_counts.get("rejected", 0)
    partially_confirmed = status_counts.get("partially_confirmed", 0)
    inconclusive = status_counts.get("inconclusive", 0)
    total = len(outcomes)
    confirmed_rate = (confirmed / total) if total else None

    root_causes = Counter(outcome.root_cause_category for outcome in outcomes if outcome.root_cause_category)
    most_common_root_cause = root_causes.most_common(1)[0][0] if root_causes else None

    history = AlertContextHistory(
        total_prior_occurrences=total,
        confirmed=confirmed,
        rejected=rejected,
        partially_confirmed=partially_confirmed,
        inconclusive=inconclusive,
        confirmed_rate=confirmed_rate,
        most_common_root_cause=most_common_root_cause,
        last_seen_at=outcomes[0].created_at if outcomes else None,
    )

    exact_match_outcomes = [
        AlertContextOutcome(
            outcome_status=outcome.outcome_status,
            root_cause_category=outcome.root_cause_category,
            resolution_summary=outcome.resolution_summary,
            confirmed_analyzers=outcome.confirmed_analyzers or [],
            rejected_analyzers=outcome.rejected_analyzers or [],
            case_id=outcome.case_id,
            resolved_at=outcome.resolved_at,
            created_at=outcome.created_at,
        )
        for outcome in outcomes[:5]
    ]

    similar_cases: list[AlertContextSimilarCase] = []
    if message and message.strip() and similarity and embedder:
        try:
            vector = embedder.encode(message.strip())
            filters = {"must": [same_metric_or_imported(metric_name)]}
            if service:
                filters["must"].append({"key": "service", "match": {"value": service}})
            results = similarity.vector_store.search(vector=vector, filters=filters, limit=5, score_threshold=0.3)
            case_ids = [result["payload"].get("case_id") for result in results if result["payload"].get("case_id")]
            case_by_id = {}
            if case_ids:
                matched_cases = db.execute(
                    select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(case_ids))
                ).scalars().all()
                case_by_id = {case.id: case for case in matched_cases}
            for result in results:
                case = case_by_id.get(result["payload"].get("case_id"))
                if not case:
                    continue
                similar_cases.append(
                    AlertContextSimilarCase(
                        case_id=case.id,
                        similarity_score=float(result["score"]),
                        title=case.case_title,
                        case_status=case.case_status,
                        outcome_status=case.outcome_status,
                        root_cause_summary=case.root_cause_summary,
                        corrective_action=case.corrective_action,
                        outcome_summary=case.outcome_summary,
                        origin="imported" if case.is_imported else "detected",
                        source=case.source,
                        source_id=case.source_id,
                        reference=f"/cases/{case.id}",
                    )
                )
        except Exception as e:
            logger.warning(f"Alert-context semantic search failed, continuing with exact-match history only: {e}")

    finding_query = select(FindingEntity).where(FindingEntity.metric_name == metric_name)
    if service:
        finding_query = finding_query.where(FindingEntity.service == service)
    findings = db.execute(
        finding_query.order_by(FindingEntity.created_at.desc()).limit(10)
    ).scalars().all()

    behavior_query = select(BehaviorFindingEntity)
    if service:
        behavior_query = behavior_query.where(BehaviorFindingEntity.service == service)
    candidate_behaviors = db.execute(
        behavior_query.order_by(BehaviorFindingEntity.created_at.desc()).limit(50)
    ).scalars().all()
    matching_behaviors = [
        behavior for behavior in candidate_behaviors
        if metric_name in (behavior.input_metrics_json or {}).values()
    ][:10]

    recent_activity = sorted(
        [(f.created_at, f.title) for f in findings] + [(b.created_at, b.title) for b in matching_behaviors],
        key=lambda item: item[0],
        reverse=True,
    )
    # finding_count/behavior_count below stay true raw counts (repeat analysis runs on the same
    # data legitimately produce multiple rows with byte-identical, deterministically-generated
    # titles) - but the titles shown to a reader are deduplicated, so "occurred 5 times" doesn't
    # collapse into the same sentence printed 5 times.
    seen_titles: set[str] = set()
    deduped_titles: list[str] = []
    for _, title in recent_activity:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        deduped_titles.append(title)
        if len(deduped_titles) == 5:
            break
    raw_activity = AlertContextRawActivity(
        finding_count=len(findings),
        behavior_count=len(matching_behaviors),
        total_occurrences=len(findings) + len(matching_behaviors),
        most_recent_at=recent_activity[0][0] if recent_activity else None,
        recent_titles=deduped_titles,
    )
    if raw_activity.total_occurrences and assistant and assistant.services.ai_services:
        evidence_lines = [
            f"Service: {service or 'unspecified'}",
            f"Metric: {metric_name}",
            f"Occurred {raw_activity.total_occurrences} time(s) recently "
            f"({raw_activity.finding_count} finding(s), {raw_activity.behavior_count} behavior(s)), "
            "no case has ever been filed for any of them.",
            "Recent titles:",
        ] + [f"- {title}" for title in raw_activity.recent_titles]
        try:
            raw_activity.ai_summary = synthesize_narrative(
                assistant.services.ai_services,
                instruction=(
                    "Summarize this recurring, never-cased activity in 1-2 plain sentences for an "
                    "engineer deciding whether a new alert on this service/metric is worth paging on. "
                    "Use ONLY the titles and counts given - do not invent a root cause, outcome, or "
                    "fix, since none has ever been recorded for these. If the titles suggest a "
                    "consistent pattern, say so; if they look mixed or unrelated, say that instead."
                ),
                evidence_text="\n".join(evidence_lines),
                max_tokens=120,
            )
        except Exception as e:
            logger.warning(f"Alert-context raw-activity AI summary failed, falling back to deterministic text: {e}")

    if total == 0 and not similar_cases:
        recommendation = "insufficient_history"
        if raw_activity.total_occurrences:
            recommendation_basis = (
                f"No resolved outcomes recorded for this service/metric, but it has occurred "
                f"{raw_activity.total_occurrences} time(s) before with no case ever filed - see raw activity below."
            )
        else:
            recommendation_basis = "No prior learning outcomes, similar cases, or raw activity found for this service/metric."
    elif total == 0 and similar_cases:
        # Still no real-vs-noise verdict (that needs resolved outcomes on this service+metric), but
        # say plainly that it has been seen before and what fixed it, rather than "insufficient".
        recommendation = "insufficient_history"
        recommendation_basis = seen_before_basis(similar_cases)
    elif confirmed_rate is not None and confirmed_rate >= 0.6:
        recommendation = "likely_real"
        recommendation_basis = (
            f"{confirmed} of {total} prior occurrences on this service+metric were confirmed real."
        )
    elif confirmed_rate is not None and confirmed_rate <= 0.3:
        recommendation = "likely_noise"
        recommendation_basis = (
            f"Only {confirmed} of {total} prior occurrences on this service+metric were confirmed real; "
            "most were rejected or inconclusive."
        )
    else:
        recommendation = "insufficient_history"
        recommendation_basis = "Prior outcomes are too mixed or too few to make a confident call; review the evidence below."

    return AlertContextResponse(
        service=service,
        metric_name=metric_name,
        history=history,
        exact_match_outcomes=exact_match_outcomes,
        similar_cases=similar_cases,
        raw_activity=raw_activity,
        recommendation=recommendation,
        recommendation_basis=recommendation_basis,
    )


def seen_before_basis(similar_cases: list[AlertContextSimilarCase]) -> str:
    imported = sum(1 for case in similar_cases if case.origin == "imported")
    count = len(similar_cases)
    found = f"{count} similar past incident{'s' if count != 1 else ''}"
    if imported:
        found += f" ({imported} imported from incident records)" if imported != count else " imported from incident records"
    top = similar_cases[0]
    lines = [f"Seen before: {found}, no real-vs-noise verdict yet. Closest: \"{top.title}\"."]
    fix = top.corrective_action or top.outcome_summary
    if top.root_cause_summary:
        lines.append(_sentence(f"Root cause then: {top.root_cause_summary}"))
    if fix:
        lines.append(_sentence(f"Fixed by: {fix}"))
    return " ".join(lines)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."
