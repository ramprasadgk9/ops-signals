"""Ask Ops Signals golden questions: the golden set must match the corpus, and documentation
answers must not regress below the recorded floors (see benchmark/assistant_benchmark.py)."""

from __future__ import annotations

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from benchmark.assistant_benchmark import PROJECT_ROOT, load_golden, validate_golden


class _ZeroEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.0] * 384


def test_golden_set_matches_the_corpus() -> None:
    documents = ApplicationKnowledgeBootstrapService(client=None, embedder=_ZeroEmbedder(), repo_root=PROJECT_ROOT)._build_documents()

    assert validate_golden(load_golden(), documents) == []
