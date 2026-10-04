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
from backend.app.assistant.passages import quote_is_in, select_passage
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
# Documentation sources per evidence group that get a quoted passage (each costs one small
# embedding batch).
QUOTED_SOURCES_PER_GROUP = 3


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

    @property
    def ai_services(self) -> OptionalAIServices | None:
        return self.services.ai_services

    @staticmethod
    def route_intents(message: str) -> list[str]:
        # The product's own name is not a question about signals: "How do I deploy Ops Signals?"
        # used to route to findings only and never searched documentation.
        text = re.sub(r"ops[\s-]?signals", " ", message.lower())
        # A quoted title names a finding or case, it doesn't say what kind of evidence is wanted:
        # 'Tell me about the finding "... baseline shift ..."' was routed to analyzer docs first.
        text = _QUOTED.sub(" ", text)
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

        # Applied after the fallback on purpose: these phrasings keep the broad fallback's searches
        # (matched earlier, "Did anything unusual happen?" would lose its documentation, case and
        # memory search) but lead with findings, which is where the answer is - "Did any metric stop
        # reporting?" used to lead with a doc about starved metrics while the stuck-metric findings
        # came third.
        if any(term in text for term in _DATA_AND_SEASONAL_TERMS) or re.search(r"\b(the|this|that) finding\b", text):
            routes = ["FINDING_SEARCH", *[route for route in routes if route != "FINDING_SEARCH"]]

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
        """Named for the search that leads the answer."""
        return _ROUTE_INTENTS.get(routes[0], "general") if routes else "general"

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
        """First occurrence of each source, in the given order - searches return best first, and a
        group's order may be reranked, which re-sorting by raw score would undo."""
        deduped: list[AssistantSource] = []
        seen: set[tuple[str, str, str, str]] = set()
        for source in sources:
            # Findings share one list link, so title and service tell two of them apart.
            key = (source.source_type, source.reference or source.title, source.title, source.service or "")
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

        docs_searched = False
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
                # Both routes search the same documentation; the second would repeat every result
                # ("24 items across Documentation, Documentation").
                if docs_searched:
                    continue
                docs_searched = True
                app_sources, used_fallback = self._application_sources(payload)
                group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=len(app_sources), sources=app_sources)
                if used_fallback:
                    if group.count:
                        fallback_groups.append(group)
                    continue
            else:
                continue

            group.sources = self._dedupe_sources(group.sources)
            group.count = len(group.sources)
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

        groups = _drop_repeated_sources(groups)
        if _is_analyzer_list_question(payload.message):
            _lead_with_analyzer_catalog(groups)
        sources = self._dedupe_sources(sorted((source for group in groups for source in group.sources), key=lambda item: item.score, reverse=True))
        knowledge_used = [group.label for group in groups]
        self._attach_quotes(payload.message, groups)

        answer, ai_synthesis_used = self._compose_answer(payload.message, groups)

        suggested_questions = self._suggest_followups(groups)

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
        # "What changed recently on trend-lab?" is about trend-lab: when the question names a
        # service these findings have, search only that service's. The name alone only nudged the
        # similarity, and other services' findings came back too.
        named = _services_named_in(payload.message, rows)
        if named:
            rows = [row for row in rows if row.service in named]
        semantic_sources = self._search_evidence_semantic(
            payload,
            rows,
            limit=payload.top_k * 5 if named else payload.top_k,
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
        limit: int | None = None,
    ) -> list[AssistantSource] | None:
        """`limit` over-fetches when `rows` is a filtered subset: hits outside it are dropped below."""
        if not indexer or not rows:
            return None
        try:
            indexer.ensure_indexed(rows, id_fn=id_fn, text_fn=text_fn, payload_fn=payload_fn)
            vector = self.services.embedder.encode(payload.message)
            results = indexer.vector_store.search(vector=vector, limit=limit or payload.top_k, score_threshold=0.2)
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
        return sources[: payload.top_k]

    def _compose_answer(self, message: str, groups: list[AssistantEvidenceGroup]) -> tuple[str, bool]:
        if not groups:
            return self._template_answer(message, groups), False
        if self.services.ai_services:
            synthesized = self._synthesize_with_llm(message, groups)
            if synthesized:
                return synthesized, True
        return self._template_answer(message, groups), False

    def _attach_quotes(self, message: str, groups: list[AssistantEvidenceGroup]) -> None:
        """Sets `quote` on the leading documentation sources: the passage of the matched section
        that answers the question, word for word."""
        for group in groups:
            if group.source_type != "app_documentation":
                continue
            for source in group.sources[:QUOTED_SOURCES_PER_GROUP]:
                if source.quote is not None:
                    continue
                text = source.section_text or source.summary
                if text:
                    source.quote = select_passage(message, text, self._encode_all)

    def _encode_all(self, texts) -> list[list[float]]:
        encode_batch = getattr(self.services.embedder, "encode_batch", None)
        if encode_batch is not None:
            return encode_batch(list(texts))
        return [self.services.embedder.encode(text) for text in texts]

    def _synthesize_with_llm(self, message: str, groups: list[AssistantEvidenceGroup]) -> str | None:
        numbered = self._prompt_sources(groups)
        synthesized = synthesize_narrative(
            self.services.ai_services,
            instruction=(
                "You are the Ops Signals operational assistant. Answer the user's question using ONLY "
                "the numbered evidence below - never invent services, metrics, numbers, commands, or "
                "facts that are not in the evidence. If the evidence only partially answers the "
                "question, say so plainly instead of filling the gap yourself. Write 1-3 concise "
                "sentences in a plain operational tone. Then, on separate lines, quote word for word "
                "the one or two passages from the evidence that support your answer, each as "
                '[number] "exact text copied from that evidence item". Do not paraphrase inside a '
                "quote. Do not suggest remediation actions or claim to have made any changes."
            ),
            evidence_text=f"Question: {message}\n\nEvidence:\n{self._format_evidence_for_prompt(groups)}",
            max_tokens=500,
            timeout_seconds=30,
        )
        if not synthesized:
            return None
        return self._verify_llm_quotes(synthesized, numbered)

    @staticmethod
    def _verify_llm_quotes(answer: str, numbered: list[AssistantSource]) -> str:
        """Replaces each `[n] "..."` line with the quote and a citation built from source n's own
        metadata - or drops it when the text is not actually in source n. When no quote survives,
        the deterministic quote of the top documentation source is added instead, so an AI answer
        about documentation always shows the passage it rests on."""
        prose: list[str] = []
        quotes: list[str] = []
        for line in answer.splitlines():
            match = _LLM_QUOTE.match(line)
            if not match:
                prose.append(line)
                continue
            index = int(match.group(1)) - 1
            # Small models often echo the evidence line's label ('Title" (relevance 0.52): "...')
            # in front of the text they quote; the label is ours, not part of the quote.
            text = _ECHOED_LABEL.sub("", match.group(2)).strip().strip('"“”')
            if 0 <= index < len(numbered) and quote_is_in(text, "\n".join(filter(None, [numbered[index].summary, numbered[index].section_text]))):
                quotes.append(_quote_block(text, numbered[index]))
            else:
                logger.info("Dropped an LLM quote not found in evidence [%s]: %r", match.group(1), text[:120])
        if not quotes:
            top_doc = next((source for source in numbered if source.source_type == "app_documentation" and source.quote), None)
            if top_doc:
                quotes.append(_quote_block(top_doc.quote, top_doc))
        text = "\n".join(prose).strip()
        return "\n\n".join([text, *quotes]) if quotes else text

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
    def _prompt_sources(groups: list[AssistantEvidenceGroup]) -> list[AssistantSource]:
        """The sources put in the prompt, in the order _format_evidence_for_prompt numbers them."""
        return [source for group in groups for source in group.sources[:5]]

    @staticmethod
    def _format_evidence_for_prompt(groups: list[AssistantEvidenceGroup]) -> str:
        lines: list[str] = []
        number = 0
        for group in groups:
            lines.append(f"{group.label}:")
            for source in group.sources[:5]:
                number += 1
                summary = (source.summary or "").strip()
                # A documentation chunk is one section, already sized for the embedder, and is
                # passed whole: cutting it to its first few lines dropped the answer whenever it
                # wasn't in the section's opening paragraph.
                limit = PROMPT_PASSAGE_CHARS if source.source_type == "app_documentation" else 500
                if len(summary) > limit:
                    summary = summary[:limit] + "..."
                lines.append(f'[{number}] "{_source_label(source)}" (relevance {source.score:.2f}): {summary}')
        return "\n".join(lines)

    @staticmethod
    def _template_answer(message: str, groups: list[AssistantEvidenceGroup]) -> str:
        if not groups:
            return "Summary\nI could not find strong operational evidence for that question.\n\nRecommended Next Step\nTry narrowing the question to a service, metric, analyzer, finding, or case."
        primary = groups[0]
        top = primary.sources[0] if primary.sources else None
        lines = ["Summary", f"Found {_evidence_counts(groups)}."]
        if top and top.quote:
            # Documentation: lead with the passage that answers the question and where it's from,
            # not the section's opening lines.
            lines.extend(["", _quote_block(top.quote, top)])
            also = [_source_label(source) for source in primary.sources[1:3]]
            if also:
                lines.extend(["", "Also see: " + "; ".join(also)])
        elif top:
            lines.extend([
                "",
                f"Most Relevant {primary.label[:-1] if primary.label.endswith('s') else primary.label}",
                top.title,
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
    def _suggest_followups(groups: list[AssistantEvidenceGroup]) -> list[str]:
        """Follow-up questions about what leads the answer, naming its service, metric or title so
        the next search has real terms to match. Nothing for documentation: "Also see" already
        names the next sections, and "Give an example of Security model" or "Show the RCA for
        <a doc>" were not questions anyone would ask."""
        if not groups:
            return ["What changed recently?", "Which analyzers are there and what does each find?", "How does Behavior Intelligence work?"]
        top = groups[0].sources[0]
        service = top.service if _real_service(top.service) else None
        suggestions: list[str] = []
        if top.source_type in {"case", "historical_case"}:
            suggestions.append(f"Show the RCA for {top.title}")
            if service:
                suggestions.append(f"Have we seen similar {service} issues before?")
        elif top.source_type == "finding":
            if top.metric_name:
                suggestions.append(f"What analyzer detected the {top.metric_name} change?")
            if service:
                suggestions.append(f"Any related cases for {service}?")
        elif top.source_type == "behavior" and service:
            suggestions.append(f"What signals contributed to this on {service}?")
        return list(dict.fromkeys(suggestions))[:4]

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
        if _is_analyzer_list_question(payload.message):
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
        sources = _rerank_documentation([_documentation_source(row) for row in results if _is_documentation(row)], payload.message)
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


# An LLM answer's quote line: [2] "exact text", optionally prefixed "Quote" or a list marker.
_LLM_QUOTE = re.compile(r'^\s*(?:[-*>]\s*)?(?:quote\s*)?\[(\d+)\]\s*:?\s*["“](.+)["”]\s*$', re.IGNORECASE)


_ECHOED_LABEL = re.compile(r'^.*?\(relevance [0-9.]+\):\s*')


def _source_label(source: AssistantSource) -> str:
    return f"{source.title} > {source.section}" if source.section else source.title


def _quote_block(quote: str, source: AssistantSource) -> str:
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in quote.splitlines())
    citation = f"{_source_label(source)} ({source.reference})" if source.reference else _source_label(source)
    return f"From {citation}:\n{quoted}"


_ROUTE_INTENTS = {
    "DOCUMENT_SEARCH": "documentation",
    "ANALYZER_SEARCH": "documentation",
    "CASE_SEARCH": "case_search",
    "MEMORY_SEARCH": "case_search",
    "FINDING_SEARCH": "finding_search",
    "BEHAVIOR_SEARCH": "behavior_intelligence",
}
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
_PLACEHOLDER_SERVICES = frozenset({"unknown", "none", "null", "n/a", "-"})
_SINGULAR = {"Findings": "finding", "Cases": "case", "Operational Memory": "past case", "Documentation": "documentation section", "Behavior Intelligence": "behavior"}


def _services_named_in(message: str, rows: list) -> set[str]:
    """Services of `rows` that `message` names as a whole word ("trend-lab", not "trend")."""
    lowered = message.lower()
    return {
        row.service
        for row in rows
        if _real_service(row.service) and re.search(rf"(?<![\w-]){re.escape(row.service.lower())}(?![\w-])", lowered)
    }


def _real_service(service: str | None) -> bool:
    return bool(service) and service.strip().lower() not in _PLACEHOLDER_SERVICES


def _evidence_counts(groups: list[AssistantEvidenceGroup]) -> str:
    """ "6 findings, 3 cases and 4 documentation sections" """
    parts = []
    for group in groups:
        noun = _SINGULAR.get(group.label, group.label.lower())
        parts.append(f"{group.count} {noun}{'' if group.count == 1 else 's'}")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _drop_repeated_sources(groups: list[AssistantEvidenceGroup]) -> list[AssistantEvidenceGroup]:
    """Each source once, in the first group that has it. Operational Memory searches the same case
    index as Cases, so it used to repeat the same cases as a second group."""
    seen: set[str] = set()
    kept: list[AssistantEvidenceGroup] = []
    for group in groups:
        fresh = []
        for source in group.sources:
            key = source.reference if source.reference.startswith("/cases/") else f"{source.source_type}|{source.reference}|{source.title}|{source.service or ''}"
            if key not in seen:
                seen.add(key)
                fresh.append(source)
        if fresh:
            group.sources, group.count = fresh, len(fresh)
            kept.append(group)
    return kept


def _is_analyzer_list_question(message: str) -> bool:
    """ "Which analyzers are there?", "List the available analyzers" - not "Which analyzer detected
    the cpu change?", which asks about a finding."""
    lowered = message.lower()
    if not re.search(r"\banalyzers\b", lowered) or re.search(r"\b(detect|detected|found|flagged|fired|triggered)\b", lowered):
        return False
    return any(phrase in lowered for phrase in ("what are", "which", "available", "list", "all the", "what analyzers", "how many"))


@lru_cache(maxsize=1)
def _analyzer_catalog_text() -> str:
    """The registered analyzers and what each finds, word for word as the "What Are Analyzers?"
    knowledge document states it."""
    from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService

    catalog = ApplicationKnowledgeBootstrapService(client=None, embedder=None, repo_root=Path(__file__).resolve().parents[3]).analyzer_catalog()
    lines = "\n".join(f"- {analyzer_id} ({name}): {purpose}" for analyzer_id, name, purpose in catalog)
    return f"There are {len(catalog)} registered analyzers, and what each one finds:\n{lines}"


ANALYZERS_OVERVIEW_PATH = "generated://concepts/analyzers-overview"


def _lead_with_analyzer_catalog(groups: list[AssistantEvidenceGroup]) -> None:
    """ "Which analyzers are there?" asks for the whole list, which no single quoted sentence holds -
    it used to quote one line of whichever analyzer page ranked first. The documentation group now
    leads with "What Are Analyzers?" quoting its full catalog from the analyzer registry."""
    docs = next((group for group in groups if group.source_type == "app_documentation"), None)
    try:
        catalog = _analyzer_catalog_text()
    except Exception as exc:
        logger.warning("Could not build the analyzer catalog: %s", exc)
        return
    if docs is None:
        docs = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=0, sources=[])
        groups.insert(0, docs)
    overview = next((source for source in docs.sources if source.source_path == ANALYZERS_OVERVIEW_PATH), None)
    if overview is None:
        overview = AssistantSource(
            source_type="app_documentation",
            title="What Are Analyzers?",
            score=docs.sources[0].score if docs.sources else 1.0,
            reference=ANALYZERS_OVERVIEW_PATH,
            source_path=ANALYZERS_OVERVIEW_PATH,
        )
    else:
        docs.sources.remove(overview)
    overview.summary = catalog
    overview.quote = catalog
    docs.sources.insert(0, overview)
    docs.count = len(docs.sources)
    if groups[0] is not docs:
        groups.remove(docs)
        groups.insert(0, docs)


# Documentation reranking, both chosen by sweeping the golden set (0-0.2 and 0.8-1.0):
# - a section whose heading shares the question's words gets up to this much added to its score, so
#   "Where do I point my OTel Collector?" leads with the README's OTLP setup section;
# - design and proposal docs (docs/design/) count this fraction of their score, so a plan's
#   "non-goals" section doesn't outrank the user doc describing what was built.
# Larger heading weights moved more right docs to first place but made quoted answers worse.
HEADING_MATCH_WEIGHT = 0.05
DESIGN_DOC_WEIGHT = 0.9


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _content_terms(text: str) -> set[str]:
    return {_stem(word) for word in re.findall(r"[a-z0-9_]+", text.lower()) if len(word) > 2 and word not in _RERANK_STOPWORDS}


_RERANK_STOPWORDS = frozenset("the and for with how what why does can you are there this that into from about which when where who should".split())


def _rerank_documentation(sources: list[AssistantSource], message: str) -> list[AssistantSource]:
    """Documentation sources reordered by search score adjusted as above. The shown score is left
    as the search returned it."""
    question = _content_terms(message)
    if not question or (HEADING_MATCH_WEIGHT == 0 and DESIGN_DOC_WEIGHT == 1.0):
        return sources
    def adjusted(source: AssistantSource) -> float:
        score = source.score
        if source.source_path and source.source_path.startswith("docs/design/"):
            score *= DESIGN_DOC_WEIGHT
        heading = _content_terms(f"{source.title} {source.section or ''}")
        return score + HEADING_MATCH_WEIGHT * len(question & heading) / len(question)
    return sorted(sources, key=adjusted, reverse=True)


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
        section_text=payload.get("section_text") or None,
    )


# Phrasings of data-quality and time-of-day questions ("did anything get stuck", "unusual for this
# time of day") that name no finding/analyzer keyword but are answered by findings.
_DATA_AND_SEASONAL_TERMS = (
    "stuck", "flatline", "flat line", "stopped reporting", "stopped sending", "not reporting",
    "stop reporting", "stops reporting", "stop sending", "stopped changing", "stop changing",
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
    """What to do next, for the kind of evidence that leads the answer - not for any group that
    happens to be present ("Open the highest relevance case" under an answer quoting a doc)."""
    lead = groups[0].source_type
    top = groups[0].sources[0] if groups[0].sources else None
    if lead in {"case", "historical_case"}:
        return "Open the highest relevance case and compare its RCA, timeline, and resolution with the current investigation."
    if lead == "finding":
        return "Open the relevant findings and compare the analyzer signals, severity, and affected services."
    if lead == "behavior":
        return "Review the behavior details and contributing signals before creating or updating a case."
    if top and top.reference and not top.reference.startswith("generated://"):
        return f"Read the full section in {top.reference}."
    return "Ask a narrower question about a service, metric, analyzer, finding, or case."