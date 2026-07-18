"""AI configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 30.0

    @field_validator("base_url", "model")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must not be blank")
        return value


class AIConfig(BaseModel):
    enabled: bool = False
    provider: str = "noop"
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: float = 30.0
    retry_on_invalid_output: bool = True
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)

    @field_validator("provider")
    @classmethod
    def provider_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("provider must not be blank")
        return value
