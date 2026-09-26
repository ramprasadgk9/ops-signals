"""Assistant routing and grounded response generation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.intent_service import IntentService
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.assistant.schemas import AssistantChatRequest, AssistantChatResponse, AssistantEvidenceGroup, AssistantSource
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.evidence_indexer import EvidenceMemoryIndexer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
from intelligence.analyzer_registry import load_registrations

logger = logging.getLogger(__name__)

# Minimum similarity for a documentation chunk to count as matching the question, for every client.
DOCUMENT_SCORE_FLOOR = 0.3
# Longest documentation passage put in the LLM prompt; section chunks are sized well under this.
PROMPT_PASSAGE_CHARS = 1200


@dataclass
class AssistantServices:
    embedder: Embedder
    case_similarity: SimilarityService
    docs_store: VectorStore
    ai_services: OptionalAIServices | None = None
    findings_indexer: EvidenceMemoryIndexer | None = None
    behaviors_indexer: EvidenceMemoryIndexer | None = None


class OperationalIntelligenceAssistant:
    def __init__(self, services: AssistantServices):
        self.services = services
        self.intent_service = IntentService(
            services.ai_services.structured if services.ai_services else None
        )

    @staticmethod
    def route_intents(message: str) -> list[str]:
        # The product's own name is not a question about signals: "How do I deploy Ops Signals?"
        # used to route to findings only and never searched documentation.
        text = re.sub(r"ops[\s-]?signals", " ", message.lower())
        routes: list[str] = []

        if any(keyword in text for keyword in ["case", "incident", "resolved", "resolution", "rca", "root cause", "similar", "seen this before"]):
            routes.extend(["CASE_SEARCH", "MEMORY_SEARCH"])
        if any(keyword in text for keyword in ["finding", "signal", "anomaly", "trend", "changed", "what changed", "detected"]):
            routes.append("FINDING_SEARCH")
        if any(keyword in text for keyword in ["behavior", "behaviour", "behavior intelligence", "pattern"]):
            routes.append("BEHAVIOR_SEARCH")
        if any(keyword in text for keyword in ["memory", "historical", "seen before"]):
            routes.append("MEMORY_SEARCH")
        if any(keyword in text for keyword in ["analyzer", "stumpy", "ruptures", "prophet", "baseline", "zscore", *_registered_analyzer_terms()]):
            routes.append("ANALYZER_SEARCH")
        if any(keyword in text for keyword in ["architecture", "docs", "documentation", "how does", "what does", "what is", "benchmark", "configuration", "config", "api", "qdrant", "vector db"]):
            routes.append("DOCUMENT_SEARCH")

        if not routes:
            # A question that matches none of the keyword lists above (informal phrasing, typos,
            # a first-time user's "what does this app do" question) is exactly the case where
            # leaning on semantic search over documentation - which doesn't care about exact
            # wording the way these keyword lists do - is most likely to actually help, not less.
            # Keyword-patching every new phrasing that reaches this fallback doesn't scale;
            # including DOCUMENT_SEARCH here does, because it's driven by embeddings, not strings.
            routes = ["DOCUMENT_SEARCH", "CASE_SEARCH", "FINDING_SEARCH", "MEMORY_SEARCH"]

        # Applied after the fallback on purpose: these phrasings only ever add a findings search.
        # Matched earlier, "Did anything unusual happen?" would stop reaching the broad fallback
        # above and lose its documentation, case and memory search.
        if any(term in text for term in _DATA_AND_SEASONAL_TERMS):
            routes.append("FINDING_SEARCH")

        deduped: list[str] = []
        for route in routes:
            if route not in deduped:
                deduped.append(route)
        # A question naming one specific analyzer ("What is the seasonal_anomaly analyzer?") is
        # about that analyzer, so its documentation should lead the answer rather than whichever
        # finding the findings search happened to return first. A question that names none ("What
        # analyzer detected the cpu change?") keeps its order.
        if "ANALYZER_SEARCH" in deduped and any(term in text for term in _registered_analyzer_terms()):
            deduped.remove("ANALYZER_SEARCH")
            deduped.insert(0, "ANALYZER_SEARCH")
        return deduped

    @staticmethod
    def _intent_from_routes(routes: list[str]) -> str:
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
    def detect_intent(message: str) -> str:
        return OperationalIntelligenceAssistant._intent_from_routes(OperationalIntelligenceAssistant.route_intents(message))

    def _route(self, message: str) -> list[str]:
        """Union of keyword routing (always available, deterministic) and LLM-classified
        routing (when AI is enabled). The LLM adds routes keyword-matching misses (e.g. a
        concept not in the keyword list); keyword routing stays a floor the LLM can only
        add to, never shrink - a small local model under-selecting categories for an
        obvious question (e.g. dropping DOCUMENT_SEARCH for "how does X work") must not
        silently lose evidence that deterministic routing would have found."""
        keyword_routes = self.route_intents(message)
        llm_routes = self.intent_service.classify_routes(message)
        if not llm_routes:
            return keyword_routes
        merged = list(keyword_routes)
        for route in llm_routes:
            if route not in merged:
                merged.append(route)
        return merged

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
        routes = self._route(payload.message)
        intent = self._intent_from_routes(routes)
        sources: list[AssistantSource] = []
        groups: list[AssistantEvidenceGroup] = []
        # Documentation found only by the generic fallback query (nothing matched the question
        # itself) is kept, but placed after real evidence instead of leading the answer with an
        # architecture overview when a matching finding or case exists.
        fallback_groups: list[AssistantEvidenceGroup] = []

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
                app_sources, used_fallback = self._application_sources(payload)
                group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=len(app_sources), sources=app_sources)
                if used_fallback:
                    if group.count:
                        fallback_groups.append(group)
                    continue
            else:
                continue

            if group.count:
                groups.append(group)
                sources.extend(group.sources)
        if not {"DOCUMENT_SEARCH", "ANALYZER_SEARCH"} & set(routes):
            # Documentation is searched for every question, not only ones whose wording the keyword
            # router recognises as a docs question ("What outcome categories can a resolved case
            # have?" routes to cases only, and the answer is in the docs). It goes after the routed
            # evidence, and only a real match counts - the generic fallback query is for questions
            # routed to documentation, not filler for every other question.
            try:
                app_sources, used_fallback = self._application_sources(payload)
            except Exception as exc:
                logger.warning("Supplementary documentation search failed: %s", exc)
                app_sources, used_fallback = [], True
            if app_sources and not used_fallback:
                group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=len(app_sources), sources=app_sources)
                groups.append(group)
                sources.extend(group.sources)
        for group in fallback_groups:
            groups.append(group)
            sources.extend(group.sources)

        sources = self._dedupe_sources(sources)
        knowledge_used = [group.label for group in groups]

        answer, ai_synthesis_used = self._compose_answer(payload.message, groups)

        suggested_questions = self._suggest_followups(routes, sources)

        return AssistantChatResponse(
            conversation_id=payload.conversation_id or uuid4(),
            intent=intent,
            routes=routes,
            knowledge_used=knowledge_used,
            answer=answer,
            ai_synthesis_used=ai_synthesis_used,
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
        rows = db.execute(select(OperationalCaseEntity).order_by(OperationalCaseEntity.updated_at.desc()).limit(200)).scalars().all()
        semantic_sources = self._search_cases_semantic(payload, rows)
        sources = semantic_sources if semantic_sources is not None else self._search_cases_keyword(payload, rows)
        return AssistantEvidenceGroup(source_type="case", label="Cases", count=len(sources), sources=sources)

    def _search_cases_semantic(self, payload: AssistantChatRequest, rows: list[OperationalCaseEntity]) -> list[AssistantSource] | None:
        case_similarity = self.services.case_similarity
        if not case_similarity or not rows:
            return None
        try:
            vector = self.services.embedder.encode(payload.message)
            results = case_similarity.vector_store.search(vector=vector, limit=payload.top_k, score_threshold=0.3)
        except Exception as exc:
            logger.warning("Semantic case search failed, falling back to keyword search: %s", exc)
            return None
        by_id = {case.id: case for case in rows}
        sources: list[AssistantSource] = []
        for result in results:
            case = by_id.get(result["payload"].get("case_id"))
            if not case:
                continue
            snapshot = case.finding_snapshot or {}
            sources.append(AssistantSource(
                source_type="case",
                title=case.case_title,
                score=float(result["score"]),
                reference=f"/cases/{case.id}",
                service=snapshot.get("service"),
                metric_name=snapshot.get("metric_name"),
                summary=case.root_cause_summary or case.outcome_summary or snapshot.get("summary"),
            ))
        return sources

    @staticmethod
    def _search_cases_keyword(payload: AssistantChatRequest, rows: list[OperationalCaseEntity]) -> list[AssistantSource]:
        terms = _query_terms(payload.message)
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
        return sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]

    def _search_findings(self, payload: AssistantChatRequest, db: Session) -> AssistantEvidenceGroup:
        rows = db.execute(select(FindingEntity).order_by(FindingEntity.created_at.desc()).limit(200)).scalars().all()
        semantic_sources = self._search_evidence_semantic(
            payload,
            rows,
            indexer=self.services.findings_indexer,
            id_fn=lambda finding: finding.id,
            text_fn=lambda finding: " ".join([finding.title, finding.summary, finding.category, finding.health_status, finding.metric_name, finding.service or ""]),
            payload_fn=lambda finding: {"row_id": finding.id},
            to_source=lambda finding, score: AssistantSource(
                source_type="finding",
                title=finding.title,
                score=score,
                reference="/findings?window=7d",
                service=finding.service,
                metric_name=finding.metric_name,
                summary=f"{finding.health_status} · {finding.category} · {finding.summary}",
            ),
        )
        sources = semantic_sources if semantic_sources is not None else self._search_findings_keyword(payload, rows)
        return AssistantEvidenceGroup(source_type="finding", label="Findings", count=len(sources), sources=sources)

    @staticmethod
    def _search_findings_keyword(payload: AssistantChatRequest, rows: list[FindingEntity]) -> list[AssistantSource]:
        terms = _query_terms(payload.message)
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
                reference="/findings?window=7d",
                service=finding.service,
                metric_name=finding.metric_name,
                summary=f"{finding.health_status} · {finding.category} · {finding.summary}",
            ))
        return sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]

    def _search_behaviors(self, payload: AssistantChatRequest, db: Session) -> AssistantEvidenceGroup:
        rows = db.execute(select(BehaviorFindingEntity).order_by(BehaviorFindingEntity.created_at.desc()).limit(200)).scalars().all()
        semantic_sources = self._search_evidence_semantic(
            payload,
            rows,
            indexer=self.services.behaviors_indexer,
            id_fn=lambda behavior: behavior.id,
            text_fn=lambda behavior: " ".join([behavior.title, behavior.summary, behavior.category, behavior.severity, behavior.service or ""]),
            payload_fn=lambda behavior: {"row_id": behavior.id},
            to_source=lambda behavior, score: AssistantSource(
                source_type="behavior",
                title=behavior.title,
                score=score,
                reference="/behavior-intelligence",
                service=behavior.service,
                summary=f"{behavior.severity} · {behavior.category} · {behavior.summary}",
            ),
        )
        sources = semantic_sources if semantic_sources is not None else self._search_behaviors_keyword(payload, rows)
        return AssistantEvidenceGroup(source_type="behavior", label="Behavior Intelligence", count=len(sources), sources=sources)

    @staticmethod
    def _search_behaviors_keyword(payload: AssistantChatRequest, rows: list[BehaviorFindingEntity]) -> list[AssistantSource]:
        terms = _query_terms(payload.message)
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
        return sorted(sources, key=lambda item: item.score, reverse=True)[: payload.top_k]

    def _search_evidence_semantic(
        self,
        payload: AssistantChatRequest,
        rows: list,
        *,
        indexer: EvidenceMemoryIndexer | None,
        id_fn,
        text_fn,
        payload_fn,
        to_source,
    ) -> list[AssistantSource] | None:
        if not indexer or not rows:
            return None
        try:
            indexer.ensure_indexed(rows, id_fn=id_fn, text_fn=text_fn, payload_fn=payload_fn)
            vector = self.services.embedder.encode(payload.message)
            results = indexer.vector_store.search(vector=vector, limit=payload.top_k, score_threshold=0.2)
        except Exception as exc:
            logger.warning("Semantic evidence search against %s failed, falling back to keyword search: %s", indexer.collection_name, exc)
            return None
        by_id = {id_fn(row): row for row in rows}
        sources: list[AssistantSource] = []
        for result in results:
            row = by_id.get(result["payload"].get("row_id"))
            if not row:
                continue
            sources.append(to_source(row, float(result["score"])))
        return sources

    def _compose_answer(self, message: str, groups: list[AssistantEvidenceGroup]) -> tuple[str, bool]:
        if not groups:
            return self._template_answer(message, groups), False
        if self.services.ai_services:
            synthesized = self._synthesize_with_llm(message, groups)
            if synthesized:
                return synthesized, True
        return self._template_answer(message, groups), False

    def _synthesize_with_llm(self, message: str, groups: list[AssistantEvidenceGroup]) -> str | None:
        return self.synthesize_from_evidence(message, self._format_evidence_for_prompt(groups))

    def synthesize_from_evidence(self, question: str, evidence_text: str) -> str | None:
        """Shared LLM answer-synthesis entry point - any endpoint with its own retrieved
        evidence (not just this assistant's own search methods, e.g. the autonomous-run
        Q&A endpoint) can reuse this instead of hand-writing a second answer template.

        Returns None when AI is disabled, there's no evidence to ground an answer in, or
        the call fails - callers should fall back to their own deterministic answer.
        """
        return synthesize_narrative(
            self.services.ai_services,
            instruction=(
                "You are the Ops Signals operational assistant. Answer the user's question using ONLY "
                "the evidence provided below - never invent services, metrics, numbers, or facts that "
                "are not in the evidence. If the evidence only partially answers the question, say so "
                "plainly instead of filling the gap yourself. Write 2-4 concise sentences in a plain "
                "operational tone, referencing evidence by its title where relevant. Do not suggest "
                "remediation actions or claim to have made any changes."
            ),
            evidence_text=f"Question: {question}\n\nEvidence:\n{evidence_text}",
            max_tokens=400,
            timeout_seconds=20,
        )

    @staticmethod
    def _format_evidence_for_prompt(groups: list[AssistantEvidenceGroup]) -> str:
        lines: list[str] = []
        for group in groups:
            lines.append(f"{group.label}:")
            for source in group.sources[:5]:
                summary = (source.summary or "").strip()
                # A documentation chunk is one section, already sized for the embedder, and is
                # passed whole: cutting it to its first few lines dropped the answer whenever it
                # wasn't in the section's opening paragraph.
                limit = PROMPT_PASSAGE_CHARS if source.source_type == "app_documentation" else 500
                if len(summary) > limit:
                    summary = summary[:limit] + "..."
                label = f"{source.title} > {source.section}" if source.section else source.title
                lines.append(f'- "{label}" (relevance {source.score:.2f}): {summary}')
        return "\n".join(lines)

    @staticmethod
    def _template_answer(message: str, groups: list[AssistantEvidenceGroup]) -> str:
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
    def _suggest_followups(routes: list[str], sources: list[AssistantSource]) -> list[str]:
        """Generate topical follow-up questions grounded in the top retrieved source, instead of
        generic instruction phrases. Generic phrases like "Show related cases" carry no real
        search terms - a real question with a service/metric/title in it gives the next search
        (keyword or semantic) something concrete to match against."""
        if not sources:
            return ["Show recent findings", "Explain analyzers", "How does Behavior Intelligence work?"]

        top = sources[0]
        suggestions: list[str] = []

        if "CASE_SEARCH" in routes or "MEMORY_SEARCH" in routes:
            suggestions.append(f"Show the RCA for {top.title}")
            if top.service:
                suggestions.append(f"Have we seen similar {top.service} issues before?")
        if "FINDING_SEARCH" in routes:
            if top.metric_name:
                suggestions.append(f"What analyzer detected the {top.metric_name} change?")
            if top.service:
                suggestions.append(f"Any related cases for {top.service}?")
        if "BEHAVIOR_SEARCH" in routes and top.service:
            suggestions.append(f"What signals contributed to this on {top.service}?")
        if "DOCUMENT_SEARCH" in routes or "ANALYZER_SEARCH" in routes:
            suggestions.append(f"Give an example of {top.title}")

        deduped: list[str] = []
        for suggestion in suggestions:
            if suggestion not in deduped:
                deduped.append(suggestion)
        if not deduped:
            deduped.append(f"Tell me more about {top.title}")
        return deduped[:4]

    def _answer_historical(self, payload: AssistantChatRequest, db: Session) -> tuple[list[AssistantSource], str]:
        if not self.services.case_similarity:
            return [], "Operational memory is not available."
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
        sources, _ = self._application_sources(payload)
        if not sources:
            return sources, "I could not find a relevant documentation match."
        top = sources[0]
        return sources, f"Documentation match found in {top.title}. I used the repository docs and architecture notes to answer this question."

    def _application_sources(self, payload: AssistantChatRequest) -> tuple[list[AssistantSource], bool]:
        """Documentation matching the question, and whether it came only from the generic
        fallback query because nothing matched the question itself."""
        query_text = payload.message
        lowered = payload.message.lower()
        if "analyzer" in lowered and any(phrase in lowered for phrase in ("what are", "which", "available", "list")):
            query_text = "What are analyzers? analyzer concept analyzer registry signals findings behaviors architecture"
        elif "behavior intelligence" in lowered:
            query_text = "Behavior intelligence behavior definitions signals findings correlation architecture"
        elif "architecture" in lowered:
            # Only an explicit architecture question gets the canned architecture query. "How does X
            # work?" used to be rewritten too, which threw away X - "How does data_health detect
            # gaps?" came back as the architecture overview. Those now search on the question itself.
            query_text = "Operational Intelligence architecture PostgreSQL Qdrant analyzer registry signals findings cases"
        vector = self.services.embedder.encode(query_text)
        # A fixed floor, deliberately not payload.minimum_score: that field is the case-memory
        # similarity threshold, and each client sends its own (web 0.35, Grafana 0.4, MCP and the
        # API default 0.55), so the same question used to find different documentation depending on
        # where it was asked. A good match for a casual question ("Application Overview" against
        # "whats use of this application") scores ~0.38 with this embedding model.
        results = self.services.docs_store.search(vector=vector, limit=payload.top_k * 2, score_threshold=DOCUMENT_SCORE_FLOOR)
        sources = [_documentation_source(row) for row in results if _is_documentation(row)]
        used_fallback = False
        if not sources:
            used_fallback = True
            fallback_results = self.services.docs_store.search(
                vector=self.services.embedder.encode("Analyzers, behavior intelligence, architecture, configuration, storage, Qdrant, PostgreSQL"),
                limit=payload.top_k * 2,
                score_threshold=0.35,
            )
            sources = [_documentation_source(row) for row in fallback_results if _is_documentation(row)]
        return sources, used_fallback


def _is_documentation(row: dict) -> bool:
    return row.get("payload", {}).get("source_type") in {"generated", "repo", "app_documentation"}


def _documentation_source(row: dict) -> AssistantSource:
    payload = row["payload"]
    return AssistantSource(
        source_type="app_documentation",
        title=payload.get("title", "Documentation"),
        score=float(row["score"]),
        reference=payload.get("reference") or payload.get("source_path", ""),
        summary=payload.get("summary"),
        source_path=payload.get("source_path") or None,
        section=payload.get("section") or None,
    )


# Phrasings of data-quality and time-of-day questions ("did anything get stuck", "unusual for this
# time of day") that name no finding/analyzer keyword but are answered by findings.
_DATA_AND_SEASONAL_TERMS = (
    "stuck", "flatline", "flat line", "stopped reporting", "stopped sending", "not reporting",
    "missing data", "data gap", "data quality", "time of day", "seasonal", "unusual",
)


@lru_cache(maxsize=1)
def _registered_analyzer_terms() -> tuple[str, ...]:
    """Every registered analyzer's id and display name, lower-cased - "seasonal_anomaly" and
    "seasonal anomaly", "data_health" and "data health" - so a question naming any analyzer that
    can run, including one added through the Add Analyzer wizard, is routed to analyzer docs.
    Only multi-word or underscored terms are kept: a one-word id is either an ordinary word
    ("trend", which would pull analyzer docs into every trend question) or already a keyword above.
    Read once per process; the registry is only reloaded on restart anyway."""
    registry_dir = Path(__file__).resolve().parents[3] / "config" / "analyzer_registry.d"
    terms: set[str] = set()
    for registration in load_registrations(registry_dir):
        terms.update({registration.analyzer_id.lower(), registration.analyzer_id.replace("_", " ").lower(), registration.display_name.lower()})
    return tuple(sorted(term for term in terms if any(separator in term for separator in ("_", " ", "-"))))

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
