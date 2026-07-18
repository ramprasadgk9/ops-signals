"""AI integration exceptions."""

from __future__ import annotations


class AIError(RuntimeError):
    pass


class LLMDisabledError(AIError):
    pass


class LLMRequestError(AIError):
    pass


class AIResponseFormatError(AIError):
    pass
