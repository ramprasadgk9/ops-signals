"""Factory helpers for optional AI integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from backend.app.ai.config import AIConfig
from backend.app.ai.exceptions import LLMDisabledError, LLMRequestError
from backend.app.ai.interfaces import LLMClient
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.ai.providers import anthropic as anthropic_provider
from backend.app.ai.providers.anthropic import AnthropicLLMClient
from backend.app.ai.providers.ollama import OllamaLLMClient
from backend.app.ai.providers.openai_compatible import OpenAICompatibleLLMClient
from backend.app.ai.providers.recorded import RecordedLLMClient, RecordingLLMClient
from backend.app.ai.models import StructuredLLMService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OptionalAIServices:
    client: LLMClient
    structured: StructuredLLMService


PROVIDERS = ("ollama", "openai_compatible", "anthropic", "recorded")


def normalized_provider(config: AIConfig) -> str:
    provider = config.provider.lower().strip()
    return "openai_compatible" if provider == "openai" else provider


def llm_client_issue(config: AIConfig | None) -> str | None:
    """Why AI can't run with this config, or None when it can (or AI is simply off)."""
    if config is None:
        return "The AI configuration could not be loaded; check the ai: block in config.yaml."
    if not config.enabled:
        return None
    provider = normalized_provider(config)
    if provider == "openai_compatible":
        missing = [name for name in ("base_url", "model") if not getattr(config.openai_compatible, name)]
        if missing:
            return f"The openai_compatible provider needs {' and '.join(missing)} (OPS_SIGNALS_OPENAI_BASE_URL, OPS_SIGNALS_OPENAI_MODEL)."
        return None
    if provider == "anthropic":
        if anthropic_provider.anthropic is None:
            return "The anthropic package is not installed; run: pip install anthropic"
        return None
    if provider == "ollama":
        return None
    if provider == "recorded":
        if not Path(config.recorded.file).exists():
            return f"The recorded provider's answers file {config.recorded.file} doesn't exist (OPS_SIGNALS_AI_RECORDED_FILE)."
        return None
    return f"Unknown AI provider {config.provider!r}. Use one of: {', '.join(PROVIDERS)}."


def build_llm_client(config: AIConfig | None) -> LLMClient:
    client = _build_provider_client(config)
    if config and config.enabled and config.record_to and not isinstance(client, (NoOpLLMClient, RecordedLLMClient)):
        logger.info("Recording AI answers to %s", config.record_to)
        return RecordingLLMClient(client, config.record_to, model=getattr(client, "model", None))
    return client


def _build_provider_client(config: AIConfig | None) -> LLMClient:
    if not config or not config.enabled:
        return NoOpLLMClient()
    issue = llm_client_issue(config)
    if issue:
        logger.warning("%s Running without an LLM.", issue)
        return NoOpLLMClient()
    provider = normalized_provider(config)
    if provider == "recorded":
        return RecordedLLMClient(config.recorded.file)
    if provider == "ollama":
        return OllamaLLMClient(
            base_url=config.ollama.base_url,
            model=config.ollama.model,
            timeout_seconds=config.timeout_seconds or config.ollama.timeout_seconds,
            min_timeout_seconds=config.ollama.min_timeout_seconds,
        )
    if provider == "openai_compatible":
        settings = config.openai_compatible
        return OpenAICompatibleLLMClient(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            api_key_header=settings.api_key_header,
            headers=settings.headers,
            json_mode=settings.json_mode,
            timeout_seconds=settings.timeout_seconds,
        )
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


def build_optional_ai_services(config: AIConfig | None) -> OptionalAIServices | None:
    if not config or not config.enabled:
        return None
    client = build_llm_client(config)
    return OptionalAIServices(client=client, structured=StructuredLLMService(client, retry_on_invalid_output=config.retry_on_invalid_output))
