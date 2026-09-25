from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.assistant.schemas import AssistantChatRequest, AssistantEvidenceGroup, AssistantSource
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTE = OperationalIntelligenceAssistant.route_intents


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.texts.append(text)
        return [0.1, 0.2, 0.3]


class _DocsStore:
    """Returns nothing for the question itself, and `fallback_rows` for the generic fallback query."""

    def __init__(self, fallback_rows: list[dict]) -> None:
        self.fallback_rows = fallback_rows
        self.calls = 0

    def search(self, vector, limit=5, score_threshold=0.0, filters=None):
        self.calls += 1
        return [] if self.calls == 1 else self.fallback_rows


def _assistant(embedder=None, docs_store=None) -> OperationalIntelligenceAssistant:
    return OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=embedder or _RecordingEmbedder(),
            case_similarity=SimpleNamespace(vector_store=None),
            docs_store=docs_store or _DocsStore([]),
            ai_services=None,
        )
    )


# --- Knowledge documents ------------------------------------------------------------------------


def _knowledge_documents() -> dict[str, object]:
    service = ApplicationKnowledgeBootstrapService(client=None, embedder=_RecordingEmbedder(), repo_root=PROJECT_ROOT)
    return {document.document_id: document for document in service._build_documents()}


def test_every_registered_analyzer_gets_a_knowledge_document() -> None:
    documents = _knowledge_documents()

    for analyzer_id in ("baseline_shift", "ruptures", "anomaly_zscore", "pyod_outlier", "trend", "stumpy", "prophet", "data_health", "seasonal_anomaly"):
        assert f"analyzer-{analyzer_id}" in documents
    assert "seasonal_anomaly" in documents["analyzers-overview"].content
    assert "data_health" in documents["analyzers-overview"].content


def test_analyzers_without_hand_written_text_are_described_from_themselves_not_as_baseline_shift() -> None:
    documents = _knowledge_documents()
    seasonal = documents["analyzer-seasonal_anomaly"].content
    data_health = documents["analyzer-data_health"].content

    assert "Purpose: Detects values that are unusual for their time of day or week." in seasonal
    assert "STL" in seasonal
    assert "Purpose: Detects metrics that stopped reporting or stopped changing." in data_health
    assert "Required sample size: At least 100 valid samples." in seasonal
    for content in (seasonal, data_health):
        assert "Baseline shifts between the first and second half of the window" not in content


def test_hand_written_analyzer_descriptions_are_unchanged() -> None:
    ruptures = _knowledge_documents()["analyzer-ruptures"].content

    assert "Purpose: Detect persistent structural changes in time-series behavior." in ruptures


# --- Routing ------------------------------------------------------------------------------------


def test_naming_an_analyzer_routes_to_its_documentation_first() -> None:
    assert ROUTE("What is the seasonal_anomaly analyzer?")[0] == "ANALYZER_SEARCH"
    assert ROUTE("How does data health work?")[0] == "ANALYZER_SEARCH"


def test_a_question_naming_no_specific_analyzer_keeps_its_order() -> None:
    assert ROUTE("What analyzer detected the cpu change?")[0] == "FINDING_SEARCH"
    assert ROUTE("Any cases related to trend signal?") == ["CASE_SEARCH", "MEMORY_SEARCH", "FINDING_SEARCH"]


def test_data_quality_and_time_of_day_phrasing_adds_a_findings_search() -> None:
    assert "FINDING_SEARCH" in ROUTE("Was there unusual traffic for the time of day on checkout-api?")
    assert "FINDING_SEARCH" in ROUTE("Which metric got stuck?")


def test_new_terms_never_stop_a_question_reaching_the_broad_fallback() -> None:
    # "unusual" is a new term; this question used to match nothing and get the broad fallback.
    assert ROUTE("Did anything unusual happen?") == ["DOCUMENT_SEARCH", "CASE_SEARCH", "FINDING_SEARCH", "MEMORY_SEARCH"]


# --- Documentation search -----------------------------------------------------------------------


def test_how_does_questions_search_on_the_question_itself() -> None:
    embedder = _RecordingEmbedder()

    _assistant(embedder=embedder)._application_sources(AssistantChatRequest(message="How does data_health detect gaps?"))

    assert embedder.texts[0] == "How does data_health detect gaps?"


def test_which_analyzers_questions_use_the_analyzer_overview_query() -> None:
    embedder = _RecordingEmbedder()

    _assistant(embedder=embedder)._application_sources(AssistantChatRequest(message="Which analyzers are available?"))

    assert embedder.texts[0].startswith("What are analyzers?")


def test_generic_fallback_documentation_goes_after_real_evidence(monkeypatch) -> None:
    fallback_doc = {"score": 0.61, "payload": {"title": "02 Architecture", "source_type": "repo", "reference": "", "summary": "overview"}}
    assistant = _assistant(docs_store=_DocsStore([fallback_doc]))
    finding = AssistantSource(source_type="finding", title="error_rate got stuck at a constant value.", score=0.4, reference="/findings")
    monkeypatch.setattr(assistant, "_route", lambda message: ["DOCUMENT_SEARCH", "FINDING_SEARCH"])
    monkeypatch.setattr(
        assistant,
        "_search_findings",
        lambda payload, db: AssistantEvidenceGroup(source_type="finding", label="Findings", count=1, sources=[finding]),
    )

    response = assistant.chat(AssistantChatRequest(message="Did any metric get stuck?"), db=None)

    # The flat `sources` list is sorted by score (unchanged); the evidence groups and the answer's
    # lead follow the group order, which is what this change affects.
    assert [group.label for group in response.evidence_groups] == ["Findings", "Documentation"]
    assert "Most Relevant Finding\nerror_rate got stuck at a constant value." in response.answer
    assert "02 Architecture" in [source.title for source in response.sources]
