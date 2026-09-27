from __future__ import annotations

from backend.app.assistant.schemas import AssistantEvidenceGroup, AssistantSource
from backend.app.assistant.service import OperationalIntelligenceAssistant

SUGGEST = OperationalIntelligenceAssistant._suggest_followups


def _source(**overrides) -> AssistantSource:
    defaults = dict(source_type="finding", title="CPU usage baseline shifted", score=0.9, reference="/findings?window=7d", service="checkout-api", metric_name="cpu_usage", summary="...")
    defaults.update(overrides)
    return AssistantSource(**defaults)


def _led_by(*sources: AssistantSource) -> list[AssistantEvidenceGroup]:
    return [AssistantEvidenceGroup(source_type=sources[0].source_type, label="x", count=len(sources), sources=list(sources))]


def test_no_evidence_suggests_questions_that_can_be_answered() -> None:
    suggestions = SUGGEST([])

    assert suggestions
    assert all(isinstance(item, str) and item for item in suggestions)


def test_a_finding_leads_to_questions_naming_its_service_and_metric() -> None:
    suggestions = SUGGEST(_led_by(_source()))

    assert suggestions == ["What analyzer detected the cpu_usage change?", "Any related cases for checkout-api?"]


def test_a_case_leads_to_its_rca() -> None:
    suggestions = SUGGEST(_led_by(_source(source_type="case", title="Checkout CPU regression")))

    assert suggestions[0] == "Show the RCA for Checkout CPU regression"


def test_documentation_gets_no_made_up_follow_ups() -> None:
    # Used to be "Give an example of Security model" and "Show the RCA for <a doc>".
    doc = _source(source_type="app_documentation", title="Security model", service=None, metric_name=None, reference="docs/security-model.md#clients")

    assert SUGGEST(_led_by(doc)) == []


def test_the_placeholder_service_is_never_named() -> None:
    suggestions = SUGGEST(_led_by(_source(service="unknown")))

    assert not any("unknown" in item for item in suggestions)


def test_follow_ups_come_from_what_leads_not_from_every_route() -> None:
    finding = _source()
    case = _source(source_type="case", title="Checkout CPU regression")
    groups = _led_by(finding) + _led_by(case)

    assert not any("RCA" in item for item in SUGGEST(groups))
