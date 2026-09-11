"""Intent classification service."""

from __future__ import annotations

from backend.app.ai.exceptions import AIError
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService


class IntentService:
    ROUTES = ("CASE_SEARCH", "MEMORY_SEARCH", "FINDING_SEARCH", "BEHAVIOR_SEARCH", "ANALYZER_SEARCH", "DOCUMENT_SEARCH")

    def __init__(self, structured: StructuredLLMService | None = None) -> None:
        self.structured = structured

    def classify_routes(self, message: str) -> list[str] | None:
        """LLM-backed replacement for keyword-based evidence routing.

        Returns None when AI is unavailable or the call fails, so the caller can fall
        back to keyword routing rather than treating "no routes" as a real answer.
        """
        if not self.structured:
            return None
        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "Classify which operational-intelligence evidence categories the user's question needs. "
                        "Choose one or more of: CASE_SEARCH (past incidents/cases), MEMORY_SEARCH (has this "
                        "happened before / historical match), FINDING_SEARCH (current findings, signals, "
                        "anomalies, what changed), BEHAVIOR_SEARCH (behavior intelligence / cross-metric "
                        "patterns), ANALYZER_SEARCH (a specific analyzer's behavior), DOCUMENT_SEARCH (how the "
                        "app, architecture, or a concept works). Return ONLY a comma-separated list of the "
                        "matching labels, nothing else."
                    ),
                ),
                LLMMessage(role="user", content=message),
            ],
            temperature=0.0,
            max_tokens=40,
            response_format="text",
            timeout_seconds=10,
        )
        try:
            response = self.structured.client.generate(request)
        except AIError:
            return None
        routes: list[str] = []
        for token in response.content.upper().split(","):
            candidate = token.strip()
            if candidate in self.ROUTES and candidate not in routes:
                routes.append(candidate)
        return routes or None

    def classify(self, message: str) -> str:
        if not self.structured:
            text = message.lower()
            if any(keyword in text for keyword in ["analyzer", "architecture", "behavior intelligence", "config"]):
                return "application"
            if any(keyword in text for keyword in ["seen before", "similar", "historical", "resolved", "root cause"]):
                return "historical"
            return "mixed"

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="Classify the user's question as historical, application, or mixed. Return only one token."),
                LLMMessage(role="user", content=message),
            ],
            temperature=0.0,
            max_tokens=8,
            response_format="text",
            timeout_seconds=10,
        )
        try:
            response = self.structured.client.generate(request)
            normalized = response.content.strip().lower()
            if "historical" in normalized:
                return "historical"
            if "application" in normalized:
                return "application"
        except AIError:
            pass
        return self._fallback_classify(message)

    @staticmethod
    def _fallback_classify(message: str) -> str:
        text = message.lower()
        if any(keyword in text for keyword in ["analyzer", "architecture", "behavior intelligence", "config"]):
            return "application"
        if any(keyword in text for keyword in ["seen before", "similar", "historical", "resolved", "root cause"]):
            return "historical"
        return "mixed"
