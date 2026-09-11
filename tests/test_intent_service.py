from __future__ import annotations

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.ai.services.intent_service import IntentService


class _FakeLLMClient(LLMClient):
    def __init__(self, *, response: str | None = None, should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self.should_fail:
            raise LLMRequestError("simulated failure")
        return LLMResponse(content=self.response or "", model="fake-model", provider="fake")


def test_classify_routes_returns_none_when_ai_is_unavailable() -> None:
    service = IntentService(structured=None)

    assert service.classify_routes("What changed in checkout cpu?") is None


def test_classify_routes_parses_a_comma_separated_valid_response() -> None:
    client = _FakeLLMClient(response="CASE_SEARCH, MEMORY_SEARCH")
    service = IntentService(structured=StructuredLLMService(client))

    assert service.classify_routes("Have we seen this before?") == ["CASE_SEARCH", "MEMORY_SEARCH"]


def test_classify_routes_dedupes_and_ignores_unknown_labels() -> None:
    client = _FakeLLMClient(response="CASE_SEARCH, case_search, NOT_A_ROUTE, FINDING_SEARCH")
    service = IntentService(structured=StructuredLLMService(client))

    assert service.classify_routes("...") == ["CASE_SEARCH", "FINDING_SEARCH"]


def test_classify_routes_returns_none_when_response_has_no_valid_labels() -> None:
    client = _FakeLLMClient(response="I'm not sure what you mean.")
    service = IntentService(structured=StructuredLLMService(client))

    assert service.classify_routes("gibberish") is None


def test_classify_routes_returns_none_when_the_llm_call_fails() -> None:
    client = _FakeLLMClient(should_fail=True)
    service = IntentService(structured=StructuredLLMService(client))

    assert service.classify_routes("What changed in checkout cpu?") is None
