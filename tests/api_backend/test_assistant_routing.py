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
