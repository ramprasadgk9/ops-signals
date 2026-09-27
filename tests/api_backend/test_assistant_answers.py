"""How Ask Ops Signals assembles an answer: which evidence leads, no repeats, the analyzer catalog,
and a next step and follow-ups that fit what leads. One test per problem found by asking the
first-screen example questions in the running app."""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.assistant.schemas import AssistantChatRequest, AssistantEvidenceGroup, AssistantSource
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.assistant.service import (
    AssistantServices,
    OperationalIntelligenceAssistant,
    _analyzer_catalog_text,
    _rerank_documentation,
)

ROUTE = OperationalIntelligenceAssistant.route_intents


class _Embedder:
    def encode(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, findings=()):
        self.findings = list(findings)

    def execute(self, statement, *args):
        return _Rows(self.findings if FindingEntity.__tablename__ in str(statement) else [])


def _doc(path: str, section: str | None, score: float, title: str = "Doc") -> dict:
    return {"score": score, "payload": {"title": title, "source_type": "repo", "source_path": path, "section": section, "reference": f"{path}#{(section or '').lower()}", "summary": f"text of {section}"}}


def _assistant(doc_rows: list[dict] | None = None, case_rows: list[dict] | None = None) -> OperationalIntelligenceAssistant:
    return OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=_Embedder(),
            case_similarity=SimpleNamespace(vector_store=SimpleNamespace(search=lambda **_: case_rows or []), _build_filters=lambda *_: None),
            docs_store=SimpleNamespace(search=lambda **_: list(doc_rows or [])),
            ai_services=None,
        )
    )


# --- routing ---------------------------------------------------------------------------------------


def test_a_quoted_title_does_not_steer_routing() -> None:
    # "baseline shift" inside the title used to route analyzer docs first.
    assert ROUTE('Tell me about the finding "request_latency_p95 experienced a persistent baseline shift"')[0] == "FINDING_SEARCH"


def test_stop_reporting_questions_lead_with_findings() -> None:
    assert ROUTE("Did any metric stop reporting?")[0] == "FINDING_SEARCH"


def test_a_concept_question_about_findings_still_reaches_the_docs() -> None:
    assert "DOCUMENT_SEARCH" in ROUTE("What is a Finding?")


# --- no repeated evidence ------------------------------------------------------------------------------


def test_analyzer_and_docs_routes_search_the_docs_once() -> None:
    assistant = _assistant(doc_rows=[_doc("docs/04-analyzer-plugin-framework.md", "Registry Model", 0.6)])

    response = assistant.chat(AssistantChatRequest(message="How does the stumpy analyzer work in the docs?"), db=_Db())

    assert response.knowledge_used == ["Documentation"]
    assert response.answer.startswith("Summary\nFound 1 documentation section.")


def test_past_cases_are_not_repeated_as_operational_memory() -> None:
    case = OperationalCaseEntity(id=7, finding_id=1, analysis_run_id="run-1", case_title="Latency spike after deploy", finding_snapshot={}, case_status="resolved")
    rows = [{"score": 0.7, "payload": {"case_id": 7}}]
    assistant = _assistant(case_rows=rows)
    db = SimpleNamespace(execute=lambda statement, *args: _Rows([case]))

    response = assistant.chat(AssistantChatRequest(message="Any similar resolved cases?", minimum_score=0.1), db=db)

    references = [source.reference for group in response.evidence_groups for source in group.sources]
    assert references.count("/cases/7") == 1


def test_the_same_finding_is_listed_once() -> None:
    source = AssistantSource(source_type="finding", title="lab value is trending", score=0.5, reference="/findings?window=7d", service="trend-lab")

    assert len(OperationalIntelligenceAssistant._dedupe_sources([source, source.model_copy(), source.model_copy(update={"service": "other"})])) == 2


# --- analyzer catalog ------------------------------------------------------------------------------------


def test_which_analyzers_question_quotes_the_whole_catalog() -> None:
    assistant = _assistant(doc_rows=[_doc("generated://analyzers/stumpy", None, 0.7, title="Pattern Discovery Analyzer")])

    response = assistant.chat(AssistantChatRequest(message="Which analyzers are there and what does each find?"), db=_Db())

    lead = response.evidence_groups[0].sources[0]
    assert lead.title == "What Are Analyzers?"
    assert lead.quote == _analyzer_catalog_text()
    for analyzer in ("baseline_shift", "data_health", "seasonal_anomaly"):
        assert analyzer in response.answer
    assert "Current implementation status" not in response.answer


def test_a_question_about_which_analyzer_fired_is_not_a_catalog_question() -> None:
    assistant = _assistant(doc_rows=[_doc("generated://analyzers/trend", None, 0.5, title="Trend Analyzer")])

    response = assistant.chat(AssistantChatRequest(message="Which analyzers detected the cpu change?"), db=_Db())

    assert all(source.title != "What Are Analyzers?" for group in response.evidence_groups for source in group.sources)


# --- documentation ranking ------------------------------------------------------------------------------


def _source(path: str, section: str, score: float) -> AssistantSource:
    return AssistantSource(source_type="app_documentation", title="Doc", score=score, reference=path, source_path=path, section=section)


def test_design_docs_rank_below_a_close_user_doc() -> None:
    plan = _source("docs/design/otlp-metrics-ingestion-plan.md", "10. Explicit non-goals", 0.40)
    readme = _source("README.md", "9.3 OTLP Metrics Ingestion", 0.395)

    assert [source.source_path for source in _rerank_documentation([plan, readme], "Where do I point my OTel Collector?")] == ["README.md", "docs/design/otlp-metrics-ingestion-plan.md"]


def test_reranking_leaves_the_shown_score_alone() -> None:
    plan = _source("docs/design/plan.md", "Scope", 0.40)

    assert _rerank_documentation([plan], "scope")[0].score == 0.40


# --- next step and follow-ups -----------------------------------------------------------------------------


def test_a_docs_answer_points_to_its_section_not_to_a_case() -> None:
    assistant = _assistant(doc_rows=[_doc("docs/security-model.md", "Turning on authentication", 0.6, title="Security model")])

    response = assistant.chat(AssistantChatRequest(message="How do I turn on API authentication?"), db=_Db())

    assert "Read the full section in docs/security-model.md#turning on authentication." in response.answer
    assert "highest relevance case" not in response.answer
    assert "Relevance:" not in response.answer
    assert response.suggested_questions == []


# --- service filter --------------------------------------------------------------------------------------


def test_a_named_service_limits_the_finding_search_to_it() -> None:
    def finding(finding_id: int, service: str, title: str) -> FindingEntity:
        return FindingEntity(id=finding_id, title=title, summary="s", category="anomaly", health_status="critical", metric_name="cpu", service=service)

    db = _Db([finding(1, "checkout-api", "checkout cpu changed"), finding(2, "trend-lab", "lab value changed")])
    assistant = _assistant()

    response = assistant.chat(AssistantChatRequest(message="What changed recently on trend-lab?"), db=db)

    findings = next(group for group in response.evidence_groups if group.source_type == "finding")
    assert [source.service for source in findings.sources] == ["trend-lab"]
