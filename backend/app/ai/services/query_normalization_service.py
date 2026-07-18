"""Query normalization helper."""

from __future__ import annotations

from backend.app.ai.services.intent_service import IntentService


class QueryNormalizationService:
    def __init__(self, intent_service: IntentService | None = None) -> None:
        self.intent_service = intent_service or IntentService()

    def normalize(self, message: str) -> dict[str, str]:
        intent = self.intent_service.classify(message)
        return {"intent": intent, "query": message.strip()}
