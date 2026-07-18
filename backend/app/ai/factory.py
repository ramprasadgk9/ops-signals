"""Factory helpers for optional AI integration."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.ai.config import AIConfig
from backend.app.ai.exceptions import LLMDisabledError
from backend.app.ai.interfaces import LLMClient
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.ai.providers.ollama import OllamaLLMClient
from backend.app.ai.models import StructuredLLMService


@dataclass(slots=True)
class OptionalAIServices:
    client: LLMClient
    structured: StructuredLLMService


def build_llm_client(config: AIConfig | None) -> LLMClient:
    if not config or not config.enabled:
        return NoOpLLMClient()
    provider = config.provider.lower().strip()
    if provider == "ollama":
        return OllamaLLMClient(
            base_url=config.ollama.base_url,
            model=config.ollama.model,
            timeout_seconds=config.timeout_seconds or config.ollama.timeout_seconds,
        )
    return NoOpLLMClient()


def build_optional_ai_services(config: AIConfig | None) -> OptionalAIServices | None:
    if not config or not config.enabled:
        return None
    client = build_llm_client(config)
    return OptionalAIServices(client=client, structured=StructuredLLMService(client, retry_on_invalid_output=config.retry_on_invalid_output))
