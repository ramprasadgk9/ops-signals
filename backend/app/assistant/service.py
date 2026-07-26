"""Assistant routing and grounded response generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.intent_service import IntentService
from backend.app.assistant.schemas import AssistantChatRequest, AssistantChatResponse, AssistantEvidenceGroup, AssistantSource
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity


@dataclass
class AssistantServices:
    embedder: Embedder
    case_similarity: SimilarityService
    docs_store: VectorStore
    ai_services: OptionalAIServices | None = None


class OperationalIntelligenceAssistant:
    def __init__(self, services: AssistantServices):
        self.services = services
        self.intent_service = IntentService(
            services.ai_services.structured if services.ai_services else None
        )

    @staticmethod
    def route_intents(message: str) -> list[str]:
        text = message.lower()
        routes: list[str] = []

        if any(keyword in text for keyword in ["case", "incident", "resolved", "resolution", "rca", "root cause", "similar", "seen this before"]):
            routes.extend(["CASE_SEARCH", "MEMORY_SEARCH"])
        if any(keyword in text for keyword in ["finding", "signal", "anomaly", "trend", "changed", "what changed", "detected"]):
            routes.append("FINDING_SEARCH")
        if any(keyword in text for keyword in ["behavior", "behaviour", "behavior intelligence", "pattern"]):
            routes.append("BEHAVIOR_SEARCH")
        if any(keyword in text for keyword in ["memory", "historical", "seen before"]):
            routes.append("MEMORY_SEARCH")
        if any(keyword in text for keyword in ["analyzer", "stumpy", "ruptures", "prophet", "baseline", "zscore"]):
            routes.append("ANALYZER_SEARCH")
        if any(keyword in text for keyword in ["architecture", "docs", "documentation", "how does", "configuration", "config", "api", "qdrant", "vector db"]):
            routes.append("DOCUMENT_SEARCH")

        if not routes:
            routes = ["CASE_SEARCH", "FINDING_SEARCH", "MEMORY_SEARCH"]

        deduped: list[str] = []
        for route in routes:
            if route not in deduped:
                deduped.append(route)
        return deduped

    @staticmethod
    def detect_intent(message: str) -> str:
        routes = OperationalIntelligenceAssistant.route_intents(message)
        if "DOCUMENT_SEARCH" in routes and routes[0] == "DOCUMENT_SEARCH":
            return "documentation"
        if "CASE_SEARCH" in routes:
            return "case_search"
        if "FINDING_SEARCH" in routes:
            return "finding_search"
        if "BEHAVIOR_SEARCH" in routes:
            return "behavior_intelligence"
        return "general"

    @staticmethod
    def _dedupe_sources(sources: list[AssistantSource]) -> list[AssistantSource]:
        deduped: list[AssistantSource] = []
        seen: set[tuple[str, str, str]] = set()
        for source in sorted(sources, key=lambda item: item.score, reverse=True):
            key = (source.source_type, source.reference or source.title, source.title)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        return deduped

    def chat(self, payload: AssistantChatRequest, db: Session) -> AssistantChatResponse:
        routes = self.route_intents(payload.message)
        intent = self.detect_intent(payload.message)
        sources: list[AssistantSource] = []
        groups: list[AssistantEvidenceGroup] = []

        for route in routes:
            if route == "CASE_SEARCH":
                group = self._search_cases(payload, db)
            elif route == "FINDING_SEARCH":
                group = self._search_findings(payload, db)
            elif route == "BEHAVIOR_SEARCH":
                group = self._search_behaviors(payload, db)
            elif route == "MEMORY_SEARCH":
                historical_sources, _ = self._answer_historical(payload, db)
                group = AssistantEvidenceGroup(source_type="historical_case", label="Operational Memory", count=len(historical_sources), sources=historical_sources)
            elif route in {"DOCUMENT_SEARCH", "ANALYZER_SEARCH"}:
                app_sources, _ = self._answer_application(payload)
                group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=len(app_sources), sources=app_sources)
            else:
                continue

            if group.count:
                groups.append(group)
                sources.extend(group.sources)

        sources = self._dedupe_sources(sources)
        knowledge_used = [group.label for group in groups]

        answer = self._compose_operational_answer(payload.message, groups)

        suggested_questions = self._suggest_followups(routes, bool(sources))

        return AssistantChatResponse(
            conversation_id=payload.conversation_id or uuid4(),
            intent=intent,
            routes=routes,
            knowledge_used=knowledge_used,
            answer=answer,
            limitations=[
                "Answers are grounded in retrieved operational records and documentation.",
                "The assistant does not perform remediation.",
                "Similarity and retrieval are aids, not proof.",
            ],
            suggested_questions=suggested_questions[:5],
            sources=sources[:10],
            evidence_groups=groups,
        )

    def _search_cases(self, payload: AssistantChatRequest, db: Session) -> AssistantEvidenceGroup:
        terms = _query_terms(payload.message)
        rows = db.execute(select(OperationalCaseEntity).order_by(OperationalCaseEntity.updated_at.desc()).limit(200)).scalars().all()
        sources: list[AssistantSource] = []
        for case in rows:
            haystack = " ".join([
                case.case_title or "",
                case.root_cause_summary or "",
                case.outcome_summary or "",
                case.corrective_action or "",
                str(case.finding_snapshot or {}),
            ]).lower()
            score = _term_score(terms, haystack)
            if score <= 0 and terms:
                continue
            snapshot = case.finding_snapshot or {}
            sources.append(AssistantSource(
                source_type="case",
                title=case.case_title,
                score=score or 0.35,
                reference=f"/cases/{case.id}",
                service=snapshot.get("service"),
                metric_name=snapshot.get("metric_name"),
                summary=case.root_cause_summary or case.outcome_summary or snapshot.get("summary"),
            ))
        sources = sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]
        return AssistantEvidenceGroup(source_type="case", label="Cases", count=len(sources), sources=sources)

    def _search_findings(self, payload: AssistantChatRequest, db: Session) -> AssistantEvidenceGroup:
        terms = _query_terms(payload.message)
        rows = db.execute(select(FindingEntity).order_by(FindingEntity.created_at.desc()).limit(200)).scalars().all()
        sources: list[AssistantSource] = []
        for finding in rows:
            haystack = " ".join([finding.title, finding.summary, finding.category, finding.health_status, finding.metric_name, finding.service or ""]).lower()
            score = _term_score(terms, haystack)
            if score <= 0 and terms:
                continue
            sources.append(AssistantSource(
                source_type="finding",
                title=finding.title,
                score=score or 0.35,
                reference=f"/findings?window=7d",
                service=finding.service,
                metric_name=finding.metric_name,
                summary=f"{finding.health_status} · {finding.category} · {finding.summary}",
            ))
        sources = sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]
        return AssistantEvidenceGroup(source_type="finding", label="Findings", count=len(sources), sources=sources)

    def _search_behaviors(self, payload: AssistantChatRequest, db: Session) -> AssistantEvidenceGroup:
        terms = _query_terms(payload.message)
        rows = db.execute(select(BehaviorFindingEntity).order_by(BehaviorFindingEntity.created_at.desc()).limit(200)).scalars().all()
        sources: list[AssistantSource] = []
        for behavior in rows:
            haystack = " ".join([behavior.title, behavior.summary, behavior.category, behavior.severity, behavior.service or ""]).lower()
            score = _term_score(terms, haystack)
            if score <= 0 and terms:
                continue
            sources.append(AssistantSource(
                source_type="behavior",
                title=behavior.title,
                score=score or 0.35,
                reference="/behavior-intelligence",
                service=behavior.service,
                summary=f"{behavior.severity} · {behavior.category} · {behavior.summary}",
            ))
        sources = sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]
        return AssistantEvidenceGroup(source_type="behavior", label="Behavior Intelligence", count=len(sources), sources=sources)

    @staticmethod
    def _compose_operational_answer(message: str, groups: list[AssistantEvidenceGroup]) -> str:
        if not groups:
            return "Summary\nI could not find strong operational evidence for that question.\n\nRecommended Next Step\nTry narrowing the question to a service, metric, analyzer, finding, or case."
        total = sum(group.count for group in groups)
        primary = groups[0]
        top = primary.sources[0] if primary.sources else None
        lines = [
            "Summary",
            f"I found {total} relevant evidence item{'s' if total != 1 else ''} across {', '.join(group.label for group in groups)}.",
        ]
        if top:
            lines.extend([
                "",
                f"Most Relevant {primary.label[:-1] if primary.label.endswith('s') else primary.label}",
                top.title,
                f"Relevance: {top.score:.2f}",
            ])
            if top.summary:
                lines.extend(["", "Operational Insight", top.summary])
        lines.extend([
            "",
            "Recommended Next Step",
            _next_step_for_groups(groups),
        ])
        return "\n".join(lines)

    @staticmethod
    def _suggest_followups(routes: list[str], has_sources: bool) -> list[str]:
        if not has_sources:
            return ["Show recent findings", "Search operational memory", "Explain analyzers"]
        if "CASE_SEARCH" in routes or "MEMORY_SEARCH" in routes:
            return ["Open related cases", "Show RCA", "Show timeline", "Show only production cases", "Compare findings"]
        if "FINDING_SEARCH" in routes:
            return ["Compare findings", "What analyzer detected this?", "Show related cases", "Search operational memory"]
        if "DOCUMENT_SEARCH" in routes or "ANALYZER_SEARCH" in routes:
            return ["Explain analyzer", "Show configuration", "How does this work?", "Show related findings"]
        return ["Search cases", "Search findings", "Search operational memory"]

    def _answer_historical(self, payload: AssistantChatRequest, db: Session) -> tuple[list[AssistantSource], str]:
        current_case = None
        if payload.case_id is not None:
            current_case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == payload.case_id)).scalar_one_or_none()
        query_text = payload.message
        if current_case:
            query_text = "\n".join(["Operational case context:", CaseDocumentBuilder.build(current_case), "", f"User question: {payload.message}"])
        vector = self.services.embedder.encode(query_text)
        filters = self.services.case_similarity._build_filters(current_case, payload.same_service_only) if current_case else None
        results = self.services.case_similarity.vector_store.search(vector=vector, filters=filters, limit=payload.top_k * 2, score_threshold=payload.minimum_score)
        if current_case:
            results = [row for row in results if row["payload"].get("case_id") != current_case.id]
        results = results[: payload.top_k]
        ids = [row["payload"].get("case_id") for row in results if row["payload"].get("case_id")]
        cases = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(ids))).scalars().all() if ids else []
        by_id = {case.id: case for case in cases}
        sources: list[AssistantSource] = []
        for row in results:
            case_id = row["payload"].get("case_id")
            case = by_id.get(case_id)
            if not case:
                continue
            sources.append(AssistantSource(
                source_type="historical_case",
                title=case.case_title,
                score=float(row["score"]),
                reference=f"/cases/{case.id}",
                service=row["payload"].get("service"),
                metric_name=row["payload"].get("metric_name"),
                summary=case.root_cause_summary or case.outcome_summary or case.finding_snapshot.get("summary"),
            ))
        if not sources:
            return sources, "I could not find a strong historical match."
        top = sources[0]
        return sources, f"Historical match found: case {top.title} ({top.score:.2f}). Open the source cases for the evidence and resolution details."

    def _answer_application(self, payload: AssistantChatRequest) -> tuple[list[AssistantSource], str]:
        query_text = payload.message
        lowered = payload.message.lower()
        if "analyzer" in lowered and "what are" in lowered:
            query_text = "What are analyzers? analyzer concept analyzer registry signals findings behaviors architecture"
        elif "behavior intelligence" in lowered:
            query_text = "Behavior intelligence behavior definitions signals findings correlation architecture"
        elif "architecture" in lowered or "how does" in lowered:
            query_text = "Operational Intelligence architecture PostgreSQL Qdrant analyzer registry signals findings cases"
        vector = self.services.embedder.encode(query_text)
        results = self.services.docs_store.search(vector=vector, limit=payload.top_k * 2, score_threshold=max(0.4, payload.minimum_score))
        sources = [
            AssistantSource(
                source_type="app_documentation",
                title=row["payload"].get("title", "Documentation"),
                score=float(row["score"]),
                reference=row["payload"].get("reference", ""),
                summary=row["payload"].get("summary"),
            )
            for row in results
            if row.get("payload", {}).get("source_type") in {"generated", "repo", "app_documentation"}
        ]
        if not sources:
            fallback_results = self.services.docs_store.search(
                vector=self.services.embedder.encode("Analyzers, behavior intelligence, architecture, configuration, storage, Qdrant, PostgreSQL"),
                limit=payload.top_k * 2,
                score_threshold=0.35,
            )
            sources = [
                AssistantSource(
                    source_type="app_documentation",
                    title=row["payload"].get("title", "Documentation"),
                    score=float(row["score"]),
                    reference=row["payload"].get("reference", ""),
                    summary=row["payload"].get("summary"),
                )
                for row in fallback_results
                if row.get("payload", {}).get("source_type") in {"generated", "repo", "app_documentation"}
            ]
        if not sources:
            return sources, "I could not find a relevant documentation match."
        top = sources[0]
        return sources, f"Documentation match found in {top.title}. I used the repository docs and architecture notes to answer this question."


def _query_terms(message: str) -> list[str]:
    stopwords = {"the", "this", "that", "with", "from", "show", "what", "which", "about", "related", "any", "does", "case", "cases"}
    return [term for term in re.findall(r"[a-zA-Z0-9_/-]+", message.lower()) if len(term) > 2 and term not in stopwords]


def _term_score(terms: list[str], haystack: str) -> float:
    if not terms:
        return 0.0
    matched = sum(1 for term in terms if term in haystack)
    return matched / len(terms)


def _next_step_for_groups(groups: list[AssistantEvidenceGroup]) -> str:
    labels = {group.label for group in groups}
    if "Cases" in labels or "Operational Memory" in labels:
        return "Open the highest relevance case and compare its RCA, timeline, and resolution with the current investigation."
    if "Findings" in labels:
        return "Open the relevant findings and compare the analyzer signals, severity, and affected services."
    if "Behavior Intelligence" in labels:
        return "Review the behavior details and contributing signals before creating or updating a case."
    return "Open the supporting evidence and continue with a narrower operational question."
