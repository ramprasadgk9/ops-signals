"""Reusable optional AI integration layer for Operational Intelligence."""

from backend.app.ai.config import AIConfig, AnthropicConfig, OllamaConfig, OpenAICompatibleConfig, apply_ai_env_overrides
from backend.app.ai.exceptions import AIError, AIResponseFormatError, LLMDisabledError
from backend.app.ai.factory import build_llm_client, build_optional_ai_services
from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService

__all__ = [
    "AIConfig",
    "OllamaConfig",
    "OpenAICompatibleConfig",
    "AnthropicConfig",
    "apply_ai_env_overrides",
    "AIError",
    "AIResponseFormatError",
    "LLMDisabledError",
    "build_llm_client",
    "build_optional_ai_services",
    "LLMClient",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "StructuredLLMService",
]
