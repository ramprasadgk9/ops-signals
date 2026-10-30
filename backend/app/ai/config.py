"""AI configuration models."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 30.0
    # Wait at least this long for every answer, whatever limit the feature asks for (some ask 15 s).
    # For a model on CPU, which takes 10-20 s an answer; unset keeps each feature's own limit.
    min_timeout_seconds: float | None = None

    @field_validator("base_url", "model")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must not be blank")
        return value


class OpenAICompatibleConfig(BaseModel):
    """Any server that speaks the OpenAI chat completions API: vLLM, Azure OpenAI (v1 API),
    Bedrock gateways, LiteLLM, OpenAI itself. `base_url` ends at the API root, e.g. .../v1."""

    base_url: str = "http://localhost:8000/v1"
    model: str = ""
    api_key: str | None = None
    # "Authorization" sends "Bearer <key>"; any other name (Azure: "api-key") sends the key as is.
    api_key_header: str = "Authorization"
    headers: dict[str, str] = Field(default_factory=dict)
    # Send response_format=json_object when JSON is requested. Turn off for servers that reject it.
    json_mode: bool = True
    timeout_seconds: float = 30.0


class AnthropicConfig(BaseModel):
    model: str = "claude-opus-5"
    # When unset, the Anthropic SDK reads ANTHROPIC_API_KEY (or another configured credential).
    api_key: str | None = None
    base_url: str | None = None
    # low | medium | high | xhigh | max; unset uses the API default.
    effort: str | None = None
    timeout_seconds: float = 60.0


class RecordedConfig(BaseModel):
    # Answers a real model gave, replayed by the `recorded` provider (backend/app/ai/providers/recorded.py).
    file: str = "config/demo_ai/recorded_answers.json"


class AIConfig(BaseModel):
    enabled: bool = False
    # noop | ollama | openai_compatible | anthropic
    provider: str = "noop"
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: float = 30.0
    retry_on_invalid_output: bool = True
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai_compatible: OpenAICompatibleConfig = Field(default_factory=OpenAICompatibleConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    recorded: RecordedConfig = Field(default_factory=RecordedConfig)
    # Save every answer the provider gives, with its question, to this file (for `recorded`).
    record_to: str | None = None

    @field_validator("provider")
    @classmethod
    def provider_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("provider must not be blank")
        return value


def apply_ai_env_overrides(config: AIConfig) -> AIConfig:
    """Apply OPS_SIGNALS_* environment overrides on top of config.yaml values."""
    if os.getenv("OPS_SIGNALS_AI_ENABLED"):
        config.enabled = os.environ["OPS_SIGNALS_AI_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
    if os.getenv("OPS_SIGNALS_AI_PROVIDER"):
        config.provider = os.environ["OPS_SIGNALS_AI_PROVIDER"]
    if os.getenv("OPS_SIGNALS_OLLAMA_URL"):
        config.ollama.base_url = os.environ["OPS_SIGNALS_OLLAMA_URL"]
    if os.getenv("OPS_SIGNALS_OLLAMA_MODEL"):
        config.ollama.model = os.environ["OPS_SIGNALS_OLLAMA_MODEL"]
    if os.getenv("OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS"):
        config.ollama.min_timeout_seconds = float(os.environ["OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS"])
    if os.getenv("OPS_SIGNALS_AI_RECORDED_FILE"):
        config.recorded.file = os.environ["OPS_SIGNALS_AI_RECORDED_FILE"]
    if os.getenv("OPS_SIGNALS_AI_RECORD_TO"):
        config.record_to = os.environ["OPS_SIGNALS_AI_RECORD_TO"]
    if os.getenv("OPS_SIGNALS_OPENAI_BASE_URL"):
        config.openai_compatible.base_url = os.environ["OPS_SIGNALS_OPENAI_BASE_URL"]
    if os.getenv("OPS_SIGNALS_OPENAI_MODEL"):
        config.openai_compatible.model = os.environ["OPS_SIGNALS_OPENAI_MODEL"]
    if os.getenv("OPS_SIGNALS_OPENAI_API_KEY"):
        config.openai_compatible.api_key = os.environ["OPS_SIGNALS_OPENAI_API_KEY"]
    if os.getenv("OPS_SIGNALS_OPENAI_API_KEY_HEADER"):
        config.openai_compatible.api_key_header = os.environ["OPS_SIGNALS_OPENAI_API_KEY_HEADER"]
    if os.getenv("OPS_SIGNALS_ANTHROPIC_MODEL"):
        config.anthropic.model = os.environ["OPS_SIGNALS_ANTHROPIC_MODEL"]
    if os.getenv("OPS_SIGNALS_ANTHROPIC_API_KEY"):
        config.anthropic.api_key = os.environ["OPS_SIGNALS_ANTHROPIC_API_KEY"]
    return config
