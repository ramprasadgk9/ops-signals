"""Provider-neutral LLM interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: Sequence[LLMMessage]
    temperature: float = 0.0
    max_tokens: int | None = None
    response_format: str | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str | None = None
    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class LLMClient(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse:
        ...
