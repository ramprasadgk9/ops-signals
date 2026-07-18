"""Assistant routing and grounded response generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.intent_service import IntentService
from backend.app.assistant.schemas import AssistantChatRequest, AssistantChatResponse, AssistantSource
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import OperationalCaseEntity


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
    def detect_intent(message: str) -> str:
        text = message.lower()
        app_keywords = [
            "analyzer", "behavior intelligence", "architecture", "config", "configuration",
            "workflow", "api", "qdrant", "save to vector db", "vector db", "signal", "finding",
            "case", "docs", "how does", "what is the difference", "how are behaviors",
        ]
        historical_keywords = [
            "have we seen", "similar", "historical", "previously", "root cause", "resolved",
            "outcome", "incident", "case before", "what changed", "similar case",
        ]
        app_score = sum(1 for keyword in app_keywords if keyword in text)
        hist_score = sum(1 for keyword in historical_keywords if keyword in text)
        if app_score and hist_score:
            return "mixed"
        if app_score:
            return "application"
        if hist_score:
            return "historical"
        return "mixed"

    def chat(self, payload: AssistantChatRequest, db: Session) -> AssistantChatResponse:
        intent = self.intent_service.classify(payload.message) if self.services.ai_services else self.detect_intent(payload.message)
        sources: list[AssistantSource] = []
        answers: list[str] = []

        if intent in {"historical", "mixed"}:
            historical_sources, historical_answer = self._answer_historical(payload, db)
            sources.extend(historical_sources)
            if historical_answer:
                answers.append(historical_answer)

        if intent in {"application", "mixed"}:
            app_sources, app_answer = self._answer_application(payload)
            sources.extend(app_sources)
            if app_answer:
                answers.append(app_answer)

        if not answers:
            answers.append("I could not confidently route that question. Try asking about a case, a behavior, an analyzer, or the application architecture.")

        suggested_questions = [
            "Show similar historical cases",
            "What is behavior intelligence?",
            "Explain the available analyzers",
            "How does the application architecture work?",
        ]
        if payload.case_id:
            suggested_questions.insert(0, "What changed compared with this case?")

        return AssistantChatResponse(
            conversation_id=payload.conversation_id or uuid4(),
            intent=intent,
            answer="\n\n".join(answers),
            limitations=[
                "Answers are grounded in retrieved cases and documentation.",
                "The assistant does not perform remediation.",
                "Similarity and retrieval are aids, not proof.",
            ],
            suggested_questions=suggested_questions[:5],
            sources=sources[:10],
        )

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
