"""Intent classification service."""

from __future__ import annotations

from backend.app.ai.exceptions import AIError
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService


class IntentService:
    def __init__(self, structured: StructuredLLMService | None = None) -> None:
        self.structured = structured

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
