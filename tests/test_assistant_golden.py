"""Ask Ops Signals golden questions: the golden set must match the corpus, and documentation
answers must not regress below the recorded floors (see benchmark/assistant_benchmark.py)."""

from __future__ import annotations

import pytest

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from benchmark.assistant_benchmark import PROJECT_ROOT, build_assistant, evaluate, load_golden, summarize, validate_golden


class _ZeroEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.0] * 384


def test_golden_set_matches_the_corpus() -> None:
    documents = ApplicationKnowledgeBootstrapService(client=None, embedder=_ZeroEmbedder(), repo_root=PROJECT_ROOT)._build_documents()

    assert validate_golden(load_golden(), documents) == []


# One question below the scores recorded when each fix landed (33, 39, 38, 38 and 27 of 40
# scored questions): a floor is (count - 1) / scored questions, rounded down. Raise a floor when a
# change genuinely improves its metric; lowering one needs a reason in the commit message.
# section_hit@3 and answer_has_answer raised with the README split (48 and 36 of 50).
# doc_hit@1, doc_hit@3 and answer_has_answer raised with the doc-writing guide (43, 51 and 38 of 51).
# doc_hit@1 and answer_has_answer raised with the glossary (45 and 40 of 53).
FLOORS = {
    "doc_hit@1": 0.83,
    "doc_hit@3": 0.98,
    "section_hit@3": 0.94,
    "evidence_has_answer": 0.92,
    "answer_has_answer": 0.73,
}


@pytest.fixture(scope="module")
def golden_summary() -> dict[str, dict[str, float]]:
    try:
        from backend.app.memory.embedder import CaseEmbedder

        embedder = CaseEmbedder()
    except Exception as exc:
        pytest.skip(f"embedding model unavailable, golden retrieval not measured: {exc}")
    assistant, documents = build_assistant(embedder=embedder)
    return summarize(evaluate(assistant, documents, load_golden()))


@pytest.mark.parametrize("metric", sorted(FLOORS))
def test_documentation_answers_stay_above_their_floor(golden_summary, metric: str) -> None:
    for surface, metrics in golden_summary.items():
        assert metrics[metric] >= FLOORS[metric], f"{surface} {metric} {metrics[metric]:.0%} < floor {FLOORS[metric]:.0%} - run python -m benchmark.assistant_benchmark for the misses"


def test_every_client_surface_gets_the_same_documentation(golden_summary) -> None:
    assert len({tuple(sorted(metrics.items())) for metrics in golden_summary.values()}) == 1
