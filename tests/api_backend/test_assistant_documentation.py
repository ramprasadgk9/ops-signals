from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.assistant.schemas import AssistantChatRequest
from backend.app.assistant.service import DOCUMENT_SCORE_FLOOR, AssistantServices, OperationalIntelligenceAssistant

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Embedder:
    def encode(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _RecordingDocsStore:
    def __init__(self) -> None:
        self.thresholds: list[float] = []

    def search(self, vector, limit=5, score_threshold=0.0, filters=None):
        self.thresholds.append(score_threshold)
        return []


def _assistant(docs_store) -> OperationalIntelligenceAssistant:
    empty_case_store = SimpleNamespace(search=lambda **_: [])
    return OperationalIntelligenceAssistant(
        AssistantServices(embedder=_Embedder(), case_similarity=SimpleNamespace(vector_store=empty_case_store), docs_store=docs_store, ai_services=None)
    )


def _documents():
    return ApplicationKnowledgeBootstrapService(client=None, embedder=_Embedder(), repo_root=PROJECT_ROOT)._build_documents()


def test_every_knowledge_document_has_a_unique_id() -> None:
    counts = Counter(document.document_id for document in _documents())

    assert [document_id for document_id, count in counts.items() if count > 1] == []


def test_project_readme_and_docs_readme_are_separate_documents() -> None:
    paths = {document.source_path: document.document_id for document in _documents()}

    assert paths["README.md"] != paths["docs/README.md"]


def test_documentation_search_uses_the_same_floor_whatever_minimum_score_the_client_sends() -> None:
    for minimum_score in (0.35, 0.4, 0.55, 0.9):
        store = _RecordingDocsStore()
        _assistant(store)._application_sources(AssistantChatRequest(message="Is the API authenticated by default?", minimum_score=minimum_score))

        assert store.thresholds[0] == DOCUMENT_SCORE_FLOOR


# --- Section chunks and citations ---------------------------------------------------------------

from qdrant_client import QdrantClient

from backend.app.assistant.knowledge_bootstrap import CHUNK_CHARS, _chunk_document
from backend.app.assistant.markdown_sections import github_anchor, split_sections

_GUIDE = """# Setup guide

Intro paragraph. """ + "Filler sentence about setup. " * 30 + """

## Install

Run `./scripts/setup.sh`.

```bash
# not a heading
./scripts/setup.sh
```

## Security: tokens & CORS

### Clients

Send `Authorization: Bearer <token>`.
"""


def test_github_anchors_match_what_github_generates() -> None:
    assert github_anchor("6.7 Optional: Enable Local AI") == "67-optional-enable-local-ai"
    assert github_anchor("Alert Enrichment: Alertmanager → Slack") == "alert-enrichment-alertmanager--slack"
    assert github_anchor("Execution Concurrency (`max_parallel_jobs`)") == "execution-concurrency-max_parallel_jobs"


def test_a_hash_comment_inside_a_code_block_is_not_a_heading() -> None:
    headings = [section.heading for section in split_sections(_GUIDE)]

    assert "not a heading" not in headings
    assert headings == ["Setup guide", "Install", "Security: tokens & CORS", "Clients"]


def test_each_section_is_its_own_chunk_with_its_heading_path_and_anchor() -> None:
    chunks = _chunk_document(_GUIDE, "Setup guide")
    by_section = {chunk.section: chunk for chunk in chunks}

    assert "./scripts/setup.sh" in by_section["Install"].text
    assert by_section["Install"].anchor == "install"
    assert by_section["Security: tokens & CORS > Clients"].anchor == "clients"
    assert "Bearer" in by_section["Security: tokens & CORS > Clients"].text
    assert by_section["Security: tokens & CORS > Clients"].embedding_text("Setup guide").startswith("Setup guide > Security: tokens & CORS > Clients\n")


def test_no_chunk_is_longer_than_the_embedder_reads() -> None:
    for document in _documents():
        for chunk in _chunk_document(document.content, document.title):
            assert len(chunk.embedding_text(document.title)) <= CHUNK_CHARS + 10, (document.source_path, chunk.section)


class _FullSizeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.1] * ApplicationKnowledgeBootstrapService.VECTOR_SIZE


def _bootstrap(repo_root: Path, client: QdrantClient) -> None:
    ApplicationKnowledgeBootstrapService(client=client, embedder=_FullSizeEmbedder(), repo_root=repo_root).bootstrap(force=True)


def _indexed_sections(client: QdrantClient, source_path: str) -> set[str]:
    records, _ = client.scroll(collection_name=ApplicationKnowledgeBootstrapService.COLLECTION_NAME, limit=10_000, with_payload=True)
    return {record.payload["section"] for record in records if record.payload["source_path"] == source_path}


def test_a_removed_section_stops_being_searchable(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    guide = tmp_path / "docs" / "guide.md"
    guide.write_text(_GUIDE, encoding="utf-8")
    client = QdrantClient(":memory:")

    _bootstrap(tmp_path, client)
    assert "Install" in _indexed_sections(client, "docs/guide.md")

    guide.write_text(_GUIDE.split("## Install")[0] + "\n## Usage\n\nOpen the app.\n", encoding="utf-8")
    _bootstrap(tmp_path, client)

    assert _indexed_sections(client, "docs/guide.md") == {"", "Usage"}


def test_documentation_sources_cite_the_file_and_section() -> None:
    row = {
        "score": 0.61,
        "payload": {
            "title": "Security model",
            "source_type": "repo",
            "source_path": "docs/security-model.md",
            "section": "Turning on authentication",
            "reference": "docs/security-model.md#turning-on-authentication",
            "summary": "Set one shared token.",
        },
    }
    store = SimpleNamespace(search=lambda **_: [row])

    [source], _ = _assistant(store)._application_sources(AssistantChatRequest(message="How do I turn on auth?"))

    assert source.source_path == "docs/security-model.md"
    assert source.section == "Turning on authentication"
    assert source.reference == "docs/security-model.md#turning-on-authentication"


# --- Routing --------------------------------------------------------------------------------------

ROUTE = OperationalIntelligenceAssistant.route_intents


def test_the_product_name_is_not_a_question_about_signals() -> None:
    # No keyword left, so it gets the broad fallback, which leads with documentation.
    assert ROUTE("How do I deploy Ops Signals to Kubernetes?")[0] == "DOCUMENT_SEARCH"
    assert "FINDING_SEARCH" in ROUTE("Which signals fired on checkout-api?")


class _Rows:
    def scalars(self):
        return self

    def all(self):
        return []


def test_documentation_is_searched_even_when_the_question_routes_elsewhere() -> None:
    row = {"score": 0.6, "payload": {"title": "Outcome-Based Learning", "source_type": "repo", "source_path": "docs/outcome-based-learning.md", "section": "Outcome Categories", "summary": "confirmed, rejected"}}
    store = SimpleNamespace(search=lambda **_: [row])
    assistant = _assistant(store)

    response = assistant.chat(AssistantChatRequest(message="What outcome categories can a resolved case have?"), db=SimpleNamespace(execute=lambda *_: _Rows()))

    assert "DOCUMENT_SEARCH" not in response.routes
    assert response.knowledge_used == ["Documentation"]
    assert response.sources[0].section == "Outcome Categories"


def test_unmatched_supplementary_documentation_is_not_filler() -> None:
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        return [] if len(calls) == 1 else [{"score": 0.7, "payload": {"title": "Architecture", "source_type": "repo", "summary": "overview"}}]

    response = _assistant(SimpleNamespace(search=search)).chat(
        AssistantChatRequest(message="Any similar resolved cases?"), db=SimpleNamespace(execute=lambda *_: _Rows())
    )

    assert response.knowledge_used == []
