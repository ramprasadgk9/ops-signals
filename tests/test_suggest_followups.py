from __future__ import annotations

from backend.app.assistant.schemas import AssistantSource
from backend.app.assistant.service import OperationalIntelligenceAssistant


def _source(**overrides) -> AssistantSource:
    defaults = dict(source_type="finding", title="CPU usage baseline shifted", score=0.9, reference="/findings?window=7d", service="checkout-api", metric_name="cpu_usage", summary="...")
    defaults.update(overrides)
    return AssistantSource(**defaults)


def test_no_sources_returns_generic_starter_prompts_not_empty() -> None:
    suggestions = OperationalIntelligenceAssistant._suggest_followups(["FINDING_SEARCH"], [])

    assert suggestions
    assert all(isinstance(item, str) and item for item in suggestions)


def test_finding_search_suggestions_reference_the_top_source_service_and_metric() -> None:
    suggestions = OperationalIntelligenceAssistant._suggest_followups(["FINDING_SEARCH"], [_source()])

    assert any("cpu_usage" in item for item in suggestions)
    assert any("checkout-api" in item for item in suggestions)
    # Real search terms, not the old generic instruction phrases.
    assert "Show related cases" not in suggestions
    assert "Search operational memory" not in suggestions


def test_case_search_suggestions_reference_the_top_source_title() -> None:
    top = _source(source_type="case", title="Checkout CPU regression")
    suggestions = OperationalIntelligenceAssistant._suggest_followups(["CASE_SEARCH", "MEMORY_SEARCH"], [top])

    assert any("Checkout CPU regression" in item for item in suggestions)


def test_document_search_suggestions_reference_the_doc_title() -> None:
    top = _source(source_type="app_documentation", title="What Are Analyzers?", service=None, metric_name=None)
    suggestions = OperationalIntelligenceAssistant._suggest_followups(["DOCUMENT_SEARCH"], [top])

    assert any("What Are Analyzers?" in item for item in suggestions)


def test_suggestions_are_capped_and_deduplicated() -> None:
    top = _source()
    suggestions = OperationalIntelligenceAssistant._suggest_followups(
        ["CASE_SEARCH", "MEMORY_SEARCH", "FINDING_SEARCH", "BEHAVIOR_SEARCH", "DOCUMENT_SEARCH"], [top]
    )

    assert len(suggestions) <= 4
    assert len(suggestions) == len(set(suggestions))
