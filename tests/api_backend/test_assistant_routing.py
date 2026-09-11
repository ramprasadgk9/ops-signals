from backend.app.assistant.service import OperationalIntelligenceAssistant


def test_case_question_routes_to_cases_before_documentation() -> None:
    routes = OperationalIntelligenceAssistant.route_intents("Any cases related to trend signal?")

    assert routes[:3] == ["CASE_SEARCH", "MEMORY_SEARCH", "FINDING_SEARCH"]
    assert "DOCUMENT_SEARCH" not in routes
    assert OperationalIntelligenceAssistant.detect_intent("Any cases related to trend signal?") == "case_search"


def test_documentation_question_routes_to_documentation() -> None:
    routes = OperationalIntelligenceAssistant.route_intents("How does Behavior Intelligence work?")

    assert "BEHAVIOR_SEARCH" in routes
    assert "DOCUMENT_SEARCH" in routes


def test_benchmark_and_definitional_questions_route_to_documentation() -> None:
    # Regression test: live-verified gap - "What does the benchmark suite measure?" fell through
    # to the generic CASE/FINDING/MEMORY default and returned real Finding rows instead of the
    # benchmark suite docs, because neither "benchmark" nor a "what does X" phrasing matched any
    # keyword, and the LLM router didn't rescue it either.
    assert "DOCUMENT_SEARCH" in OperationalIntelligenceAssistant.route_intents("What does the benchmark suite measure?")
    assert "DOCUMENT_SEARCH" in OperationalIntelligenceAssistant.route_intents("What is a Finding?")


def test_unrecognized_phrasing_still_falls_back_to_including_documentation() -> None:
    # Regression test: live-verified gap - "whats use of this application" (informal, no
    # apostrophe) matched no keyword at all and the old fallback (CASE/FINDING/MEMORY only, never
    # DOCUMENT_SEARCH) meant a brand-new user's very first, most natural question about the app
    # got zero evidence. Keyword-patching every informal phrasing that reaches this fallback
    # doesn't scale; the fallback itself now always includes DOCUMENT_SEARCH so semantic search
    # (which doesn't care about exact wording) gets a chance to help.
    routes = OperationalIntelligenceAssistant.route_intents("whats use of this application")

    assert routes == ["DOCUMENT_SEARCH", "CASE_SEARCH", "FINDING_SEARCH", "MEMORY_SEARCH"]
    assert OperationalIntelligenceAssistant.detect_intent("whats use of this application") == "documentation"
