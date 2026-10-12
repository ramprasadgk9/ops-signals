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

    def search(self, vector, limit=5, score_threshold=0.0, filters=None, **_kwargs):
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


def test_a_table_of_contents_is_not_indexed_but_a_list_of_other_docs_is() -> None:
    # A "Contents" list names every topic, so it outranked the sections holding the answers.
    guide = (
        "# Guide\n\n" + "Intro paragraph. " * 120 + "\n\n"
        "## Contents\n\n- [Install](#install)\n- [Deploy](#deploy): [Helm](#helm) (screenshots)\n\n"
        "## Further reading\n\n- [Security model](docs/security-model.md)\n- [FAQ](docs/faq.md)\n\n"
        "## Install\n\nRun ./scripts/setup.sh and see [Deploy](#deploy) next.\n"
    )
    sections = {chunk.section for chunk in _chunk_document(guide, "Guide")}

    assert "Contents" not in sections
    assert {"Further reading", "Install"} <= sections


def test_no_chunk_is_longer_than_the_embedder_reads() -> None:
    for document in _documents():
        for chunk in _chunk_document(document.content, document.title):
            assert len(chunk.embedding_text(document.title)) <= CHUNK_CHARS + 10, (document.source_path, chunk.section)


class _FullSizeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.1] * ApplicationKnowledgeBootstrapService.VECTOR_SIZE


def _bootstrap(repo_root: Path, client: QdrantClient) -> None:
    ApplicationKnowledgeBootstrapService(client=client, embedder=_FullSizeEmbedder(), repo_root=repo_root).bootstrap()


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


def test_a_fence_closes_only_on_the_marker_that_opened_it() -> None:
    content = "# Doc\n\n~~~text\n```bash\n## not a heading\n```\n~~~\n\n## Real\n\nText.\n"

    assert [section.heading for section in split_sections(content)] == ["Doc", "Real"]


# --- Incremental reindexing -----------------------------------------------------------------------


class _CountingEmbedder:
    def __init__(self, model_name: str = "model-a") -> None:
        self.model_name = model_name
        self.texts: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.texts.append(text)
        return [0.1] * ApplicationKnowledgeBootstrapService.VECTOR_SIZE


def _repo_with_guide(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(_GUIDE, encoding="utf-8")
    return tmp_path


def _service(repo_root: Path, client: QdrantClient, embedder: _CountingEmbedder) -> ApplicationKnowledgeBootstrapService:
    return ApplicationKnowledgeBootstrapService(client=client, embedder=embedder, repo_root=repo_root)


def test_a_second_bootstrap_with_no_doc_changes_embeds_nothing(tmp_path: Path) -> None:
    repo, client = _repo_with_guide(tmp_path), QdrantClient(":memory:")
    first = _service(repo, client, _CountingEmbedder()).bootstrap()
    embedder = _CountingEmbedder()

    second = _service(repo, client, embedder).bootstrap()

    assert "docs/guide.md" in first.added
    assert (second.added, second.changed, second.removed) == ([], [], [])
    assert second.unchanged_documents == len(first.added)
    assert second.chunks_embedded == 0 and embedder.texts == []


def test_only_added_edited_and_removed_docs_are_reindexed(tmp_path: Path) -> None:
    repo, client = _repo_with_guide(tmp_path), QdrantClient(":memory:")
    (repo / "docs" / "old.md").write_text("# Old\n\nGoing away.\n", encoding="utf-8")
    _service(repo, client, _CountingEmbedder()).bootstrap()

    (repo / "docs" / "guide.md").write_text(_GUIDE + "\n## Upgrading\n\nPull and rerun setup.\n", encoding="utf-8")
    (repo / "docs" / "new.md").write_text("# New feature\n\nHow the new feature works.\n", encoding="utf-8")
    (repo / "docs" / "old.md").unlink()
    embedder = _CountingEmbedder()
    result = _service(repo, client, embedder).bootstrap()

    assert (result.added, result.changed, result.removed) == (["docs/new.md"], ["docs/guide.md"], ["docs/old.md"])
    assert all(text.startswith(("Setup guide", "New feature")) for text in embedder.texts)
    assert "Upgrading" in _indexed_sections(client, "docs/guide.md")
    assert _indexed_sections(client, "docs/old.md") == set()


def test_force_or_a_different_embedding_model_reembeds_everything(tmp_path: Path) -> None:
    repo, client = _repo_with_guide(tmp_path), QdrantClient(":memory:")
    first = _service(repo, client, _CountingEmbedder()).bootstrap()

    forced = _service(repo, client, _CountingEmbedder()).bootstrap(force=True)
    new_model = _service(repo, client, _CountingEmbedder(model_name="model-b")).bootstrap()

    assert forced.forced and sorted(forced.changed) == sorted(first.added)
    assert sorted(new_model.changed) == sorted(first.added)


def test_status_reports_the_last_bootstrap(tmp_path: Path) -> None:
    service = _service(_repo_with_guide(tmp_path), QdrantClient(":memory:"), _CountingEmbedder())
    assert service.get_status().last_bootstrap is None

    result = service.bootstrap()

    assert service.get_status().last_bootstrap is result
    assert result.started_at and result.duration_ms >= 0


def test_the_reindex_endpoint_reports_what_changed_and_status_remembers_it(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app.api import assistant as assistant_module
    from backend.app.main import create_app

    repo = _repo_with_guide(tmp_path)
    service = _service(repo, QdrantClient(":memory:"), _CountingEmbedder())
    service.bootstrap()
    (repo / "docs" / "new.md").write_text("# New feature\n\nHow it works.\n", encoding="utf-8")
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_knowledge_bootstrap] = lambda: service

    with TestClient(app) as client:
        reindex = client.post("/api/assistant/knowledge/bootstrap").json()
        status = client.get("/api/assistant/knowledge/status").json()

    assert reindex["added"] == ["docs/new.md"]
    assert reindex["changed"] == [] and reindex["removed"] == []
    assert status["last_bootstrap"]["added"] == ["docs/new.md"]


def test_status_lists_docs_changed_since_the_last_reindex_without_embedding_them(tmp_path: Path) -> None:
    repo, client = _repo_with_guide(tmp_path), QdrantClient(":memory:")
    _service(repo, client, _CountingEmbedder()).bootstrap()
    (repo / "docs" / "guide.md").write_text(_GUIDE + "\n## Upgrading\n\nPull.\n", encoding="utf-8")
    (repo / "docs" / "new.md").write_text("# New\n\nText.\n", encoding="utf-8")
    embedder = _CountingEmbedder()
    service = _service(repo, client, embedder)

    status = service.get_status()

    assert (status.pending_changes.added, status.pending_changes.changed, status.pending_changes.removed) == (["docs/new.md"], ["docs/guide.md"], [])
    assert status.document_count > 0 and embedder.texts == []

    service.bootstrap()

    after = service.get_status().pending_changes
    assert (after.added, after.changed, after.removed) == ([], [], [])


def test_status_says_whether_this_server_can_save_golden_questions(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app.api import assistant as assistant_module
    from backend.app.main import create_app

    service = _service(_repo_with_guide(tmp_path), QdrantClient(":memory:"), _CountingEmbedder())
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_knowledge_bootstrap] = lambda: service

    for flag, expected in (("false", False), ("true", True)):
        monkeypatch.setenv("OPS_SIGNALS_ALLOW_FILE_WRITES", flag)
        with TestClient(app) as client:
            assert client.get("/api/assistant/knowledge/status").json()["docs_authoring_enabled"] is expected
