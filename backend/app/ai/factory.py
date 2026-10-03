"""Factory helpers for optional AI integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.app.ai.config import AIConfig
from backend.app.ai.exceptions import LLMDisabledError, LLMRequestError
from backend.app.ai.interfaces import LLMClient
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.ai.providers.anthropic import AnthropicLLMClient
from backend.app.ai.providers.ollama import OllamaLLMClient
from backend.app.ai.providers.openai_compatible import OpenAICompatibleLLMClient
from backend.app.ai.models import StructuredLLMService

logger = logging.getLogger(__name__)


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
    if provider in {"openai_compatible", "openai"}:
        settings = config.openai_compatible
        if not settings.base_url or not settings.model:
            logger.warning("AI provider openai_compatible needs base_url and model; running without an LLM")
            return NoOpLLMClient()
        return OpenAICompatibleLLMClient(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            api_key_header=settings.api_key_header,
            headers=settings.headers,
            json_mode=settings.json_mode,
            timeout_seconds=settings.timeout_seconds,
        )
    if provider == "anthropic":
        settings = config.anthropic
        try:
            return AnthropicLLMClient(
                model=settings.model,
                api_key=settings.api_key,
                base_url=settings.base_url,
                effort=settings.effort,
                timeout_seconds=settings.timeout_seconds,
            )
        except LLMRequestError as exc:
            logger.warning("AI provider anthropic unavailable (%s); running without an LLM", exc)
            return NoOpLLMClient()
    if provider != "noop":
        logger.warning("Unknown AI provider %r; running without an LLM", config.provider)
    return NoOpLLMClient()


def build_optional_ai_services(config: AIConfig | None) -> OptionalAIServices | None:
    if not config or not config.enabled:
        return None
    client = build_llm_client(config)
    return OptionalAIServices(client=client, structured=StructuredLLMService(client, retry_on_invalid_output=config.retry_on_invalid_output))
