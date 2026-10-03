"""Which AI provider is configured, whether it is in use, and a one-request connection test.

Read-only: the provider is chosen in config.yaml or OPS_SIGNALS_* env vars and takes effect on
restart. Secrets (API keys, credentials or query strings in URLs) are never returned.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.ai.config import AIConfig
from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices, build_llm_client, llm_client_issue, normalized_provider
from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.api import assistant as assistant_module

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Populated at startup with the AIConfig the backend was started with.
_services: dict[str, AIConfig | None] = {"config": None}

ANTHROPIC_DEFAULT_ENDPOINT = "https://api.anthropic.com"
MEMORY_OFF_ISSUE = (
    "AI is configured, but operational memory is off or failed to start, so the assistant that uses AI "
    "isn't running. Check the backend log and the memory: block in config.yaml."
)


class AIStatusOut(BaseModel):
    enabled: bool
    provider: str
    model: str | None = None
    endpoint: str | None = None
    api_key_set: bool | None = None
    active: bool
    issue: str | None = None


class AITestOut(BaseModel):
    ok: bool
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    reply: str | None = None
    error: str | None = None


@router.get("/status", response_model=AIStatusOut)
def ai_status() -> AIStatusOut:
    config = _services.get("config")
    if config is None:
        return AIStatusOut(enabled=False, provider="unknown", active=False, issue=llm_client_issue(None))
    provider = normalized_provider(config)
    model, endpoint, api_key_set = _provider_details(config, provider)
    active = _active_client() is not None
    issue = llm_client_issue(config)
    if config.enabled and not issue and not active:
        issue = MEMORY_OFF_ISSUE
    return AIStatusOut(
        enabled=config.enabled,
        provider=provider,
        model=model,
        endpoint=endpoint,
        api_key_set=api_key_set,
        active=active,
        issue=issue,
    )


@router.post("/test", response_model=AITestOut)
def ai_test() -> AITestOut:
    config = _services.get("config")
    if config is None or not config.enabled:
        return AITestOut(ok=False, error="AI is off. Set OPS_SIGNALS_AI_ENABLED=1 and a provider, then restart the backend.")
    issue = llm_client_issue(config)
    if issue:
        return AITestOut(ok=False, provider=normalized_provider(config), error=issue)
    client = _active_client() or build_llm_client(config)
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Connection test. Reply with the single word: ok")],
        timeout_seconds=30.0,
    )
    try:
        response = client.generate(request)
    except AIError as exc:
        return AITestOut(ok=False, provider=normalized_provider(config), model=getattr(client, "model", None), error=str(exc))
    return AITestOut(
        ok=True,
        provider=normalized_provider(config),
        model=response.model or getattr(client, "model", None),
        latency_ms=response.latency_ms,
        reply=response.content[:200],
    )


def _active_client() -> LLMClient | None:
    assistant = assistant_module._services.get("assistant")
    services: OptionalAIServices | None = getattr(getattr(assistant, "services", None), "ai_services", None)
    if services is None or isinstance(services.client, NoOpLLMClient):
        return None
    return services.client


def _provider_details(config: AIConfig, provider: str) -> tuple[str | None, str | None, bool | None]:
    if provider == "ollama":
        return config.ollama.model, _safe_url(config.ollama.base_url), None
    if provider == "openai_compatible":
        settings = config.openai_compatible
        return settings.model or None, _safe_url(settings.base_url), bool(settings.api_key)
    if provider == "anthropic":
        settings = config.anthropic
        return settings.model, _safe_url(settings.base_url) or ANTHROPIC_DEFAULT_ENDPOINT, None
    return None, None, None


def _safe_url(url: str | None) -> str | None:
    """Drop credentials and query strings, which can carry keys."""
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
