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
    return OperationalIntelligenceAssistant(
        AssistantServices(embedder=_Embedder(), case_similarity=SimpleNamespace(vector_store=None), docs_store=docs_store, ai_services=None)
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
