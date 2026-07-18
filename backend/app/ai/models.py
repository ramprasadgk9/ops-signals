"""Structured generation helper for reusable AI workflows."""

from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.ai.exceptions import AIResponseFormatError
from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest

T = TypeVar("T", bound=BaseModel)


class StructuredLLMService:
    def __init__(self, client: LLMClient, retry_on_invalid_output: bool = True) -> None:
        self.client = client
        self.retry_on_invalid_output = retry_on_invalid_output

    def generate_structured(self, request: LLMRequest, response_model: Type[T]) -> T:
        response = self.client.generate(request)
        raw = self._strip_fences(response.content)
        try:
            return response_model.model_validate_json(raw)
        except ValidationError as exc:
            if not self.retry_on_invalid_output:
                raise AIResponseFormatError(str(exc)) from exc
            repair_request = LLMRequest(
                messages=[
                    *request.messages,
                    LLMMessage(
                        role="user",
                        content=(
                            "The previous response was invalid JSON for the requested schema. "
                            "Return only valid JSON matching the schema, with no markdown fences or prose.\n"
                            f"Validation error: {exc}"
                        ),
                    ),
                ],
                temperature=0.0,
                max_tokens=request.max_tokens,
                response_format="json",
                timeout_seconds=request.timeout_seconds,
            )
            repair_response = self.client.generate(repair_request)
            repair_raw = self._strip_fences(repair_response.content)
            try:
                return response_model.model_validate_json(repair_raw)
            except ValidationError as repair_exc:
                raise AIResponseFormatError(str(repair_exc)) from repair_exc

    @staticmethod
    def _strip_fences(content: str) -> str:
        text = content.strip()
        match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text
