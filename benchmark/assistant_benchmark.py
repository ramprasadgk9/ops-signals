"""Golden-question benchmark for Ask Ops Signals documentation answers.

Indexes the real knowledge corpus (README, docs/, generated concept and analyzer docs) with the
real embedding model into an in-memory Qdrant, asks every question in
benchmark/assistant/golden_questions.yml through `OperationalIntelligenceAssistant.chat()` once
per client surface (each sends its own top_k/minimum_score), and scores:

- doc_hit@1 / doc_hit@3: an expected file is the first / among the first three documentation
  sources returned.
- section_hit@3: an expected file *and section* is among the first three. Needs sources that
  carry a section; a source without one never counts.
- evidence_has_answer: every `contains` phrase is in the evidence text the LLM would be given.
- answer_has_answer: every `contains` phrase is in the answer text returned with AI off.

    python -m benchmark.assistant_benchmark
    python -m benchmark.assistant_benchmark --ai       # also synthesize with the configured LLM
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService, ApplicationKnowledgeDocument
from backend.app.assistant.golden import UNSCORED_CATEGORIES, Expectation, GoldenQuestion, contains_all, load_golden, validate_golden
from backend.app.assistant.schemas import AssistantChatRequest, AssistantSource
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "benchmark" / "reports"

# What each client actually sends: MemoryChatPage.tsx, grafana/backendClient.ts, and the
# AssistantChatRequest defaults that MCP and direct API callers get.
SURFACES: dict[str, dict[str, Any]] = {
    "web": {"top_k": 6, "minimum_score": 0.35},
    "grafana": {"top_k": 5, "minimum_score": 0.4},
    "api": {},
}
SCORED_METRICS = ("doc_hit@1", "doc_hit@3", "section_hit@3", "evidence_has_answer", "answer_has_answer")


@dataclass(slots=True)
class CitedSource:
    source_path: str
    section: str
    score: float


@dataclass(slots=True)
class QuestionResult:
    id: str
    category: str
    surface: str
    checks: dict[str, bool]
    top_sources: list[CitedSource]


class _EmptyRows:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None


class _EmptyDb:
    """Stands in for a database with no cases, findings or behaviors - this benchmark scores
    documentation answers only."""

    def execute(self, *_args, **_kwargs):
        return _EmptyRows()


class _EmptyVectorStore:
    def search(self, *_args, **_kwargs):
        return []


def build_assistant(embedder=None, ai_services=None) -> tuple[OperationalIntelligenceAssistant, list[ApplicationKnowledgeDocument]]:
    from qdrant_client import QdrantClient

    from backend.app.memory.embedder import CaseEmbedder
    from backend.app.memory.vector_store import QdrantVectorStore

    embedder = embedder or CaseEmbedder()
    client = QdrantClient(":memory:")
    bootstrap = ApplicationKnowledgeBootstrapService(client=client, embedder=embedder, repo_root=PROJECT_ROOT)
    bootstrap.bootstrap(force=True)
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=embedder,
            case_similarity=SimpleNamespace(vector_store=_EmptyVectorStore(), _build_filters=lambda *_: None),
            docs_store=QdrantVectorStore(client=client, collection_name=bootstrap.COLLECTION_NAME),
            ai_services=ai_services,
        )
    )
    return assistant, bootstrap._build_documents()


def _cited(source: AssistantSource, title_to_paths: dict[str, list[str]]) -> list[CitedSource]:
    path = getattr(source, "source_path", None)
    section = getattr(source, "section", None) or ""
    if path:
        return [CitedSource(source_path=path, section=section, score=round(source.score, 3))]
    # Sources from before citations carried a path: resolve the title back to its document(s).
    return [CitedSource(source_path=candidate, section=section, score=round(source.score, 3)) for candidate in title_to_paths.get(source.title, [])]


def _matches(cited: CitedSource, expectation: Expectation, need_section: bool) -> bool:
    if cited.source_path != expectation.source:
        return False
    if not need_section or expectation.section is None:
        return True
    return expectation.section.lower() in cited.section.lower()


def evaluate(
    assistant: OperationalIntelligenceAssistant,
    documents: list[ApplicationKnowledgeDocument],
    questions: list[GoldenQuestion],
    surfaces: dict[str, dict[str, Any]] = SURFACES,
) -> list[QuestionResult]:
    title_to_paths: dict[str, list[str]] = {}
    for document in documents:
        title_to_paths.setdefault(document.title, []).append(document.source_path)

    results: list[QuestionResult] = []
    for surface, params in surfaces.items():
        for question in questions:
            response = assistant.chat(AssistantChatRequest(message=question.question, **params), db=_EmptyDb())
            # In the order the answer uses them (the documentation group's, which may be reranked).
            doc_sources = next((group.sources for group in response.evidence_groups if group.source_type == "app_documentation"), [])
            ranked: list[list[CitedSource]] = [_cited(source, title_to_paths) for source in doc_sources]
            top_sources = [cited for group in ranked for cited in group]

            def hit_within(depth: int, need_section: bool) -> bool:
                return any(
                    _matches(cited, expectation, need_section)
                    for group in ranked[:depth]
                    for cited in group
                    for expectation in question.expect
                )

            evidence_text = assistant._format_evidence_for_prompt(response.evidence_groups)
            checks = {
                "doc_hit@1": hit_within(1, need_section=False),
                "doc_hit@3": hit_within(3, need_section=False),
                "section_hit@3": hit_within(3, need_section=True),
                "evidence_has_answer": bool(question.contains) and contains_all(evidence_text, question.contains),
                "answer_has_answer": bool(question.contains) and contains_all(response.answer, question.contains),
            }
            results.append(QuestionResult(id=question.id, category=question.category, surface=surface, checks=checks, top_sources=top_sources[:3]))
    return results


def summarize(results: list[QuestionResult]) -> dict[str, dict[str, float]]:
    """Per surface, the fraction of scored questions passing each check."""
    summary: dict[str, dict[str, float]] = {}
    for surface in dict.fromkeys(result.surface for result in results):
        scored = [result for result in results if result.surface == surface and result.category not in UNSCORED_CATEGORIES]
        summary[surface] = {
            metric: round(sum(result.checks[metric] for result in scored) / len(scored), 3) if scored else 0.0
            for metric in SCORED_METRICS
        }
        summary[surface]["questions"] = len(scored)
    return summary


def render_markdown(summary: dict[str, dict[str, float]], results: list[QuestionResult]) -> str:
    lines = ["# Ask Ops Signals golden questions", "", "| Surface | Questions | " + " | ".join(SCORED_METRICS) + " |", "| --- | --- |" + " --- |" * len(SCORED_METRICS)]
    for surface, metrics in summary.items():
        lines.append(f"| {surface} | {int(metrics['questions'])} | " + " | ".join(f"{metrics[metric]:.0%}" for metric in SCORED_METRICS) + " |")
        if "llm_quotes_dropped" in metrics:
            lines.extend(["", f"LLM quotes dropped as not found in the evidence: {metrics['llm_quotes_dropped']}"])
    lines.extend(["", "## Misses (web surface)", "", "| Question | Failed checks | Top sources |", "| --- | --- | --- |"])
    for result in results:
        if result.surface != "web":
            continue
        failed = [metric for metric, passed in result.checks.items() if not passed]
        if result.category == "known_gap" and result.checks["section_hit@3"]:
            lines.append(f"| {result.id} | known gap now cites its section - promote it to category docs | |")
            continue
        if result.category in UNSCORED_CATEGORIES or failed:
            top = "<br>".join(f"{cited.source_path} {('> ' + cited.section) if cited.section else ''} ({cited.score})" for cited in result.top_sources) or "none"
            label = {"out_of_scope": "report only", "known_gap": "known gap"}.get(result.category, ", ".join(failed))
            lines.append(f"| {result.id} | {label} | {top} |")
    return "\n".join(lines) + "\n"


class _DroppedQuoteCounter(logging.Handler):
    """Counts LLM quotes the assistant rejected for not appearing in the evidence."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith("Dropped an LLM quote"):
            self.count += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ai", action="store_true", help="synthesize answers with the configured LLM (OPS_SIGNALS_AI_*)")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args()

    ai_services = None
    if args.ai:
        from backend.app.ai.factory import build_optional_ai_services
        from backend.app.mcp_runtime import load_ai_config

        ai_services = build_optional_ai_services(load_ai_config())
        if ai_services is None:
            raise SystemExit("--ai given but no AI provider is configured (set OPS_SIGNALS_AI_ENABLED=1 and a provider)")

    questions = load_golden()
    assistant, documents = build_assistant(ai_services=ai_services)
    errors = validate_golden(questions, documents)
    if errors:
        raise SystemExit("Golden set does not match the corpus:\n" + "\n".join(errors))

    dropped = _DroppedQuoteCounter()
    logging.getLogger("backend.app.assistant.service").addHandler(dropped)
    logging.getLogger("backend.app.assistant.service").setLevel(logging.INFO)
    # Every surface asks the same documentation search now; one is enough when each answer is an LLM call.
    results = evaluate(assistant, documents, questions, {"web": SURFACES["web"]} if args.ai else SURFACES)
    summary = summarize(results)
    if args.ai:
        summary["web"]["llm_quotes_dropped"] = dropped.count
    suffix = "_ai" if args.ai else ""
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / f"assistant_golden{suffix}.json").write_text(
        json.dumps({"summary": summary, "results": [asdict(result) for result in results]}, indent=2) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(summary, results)
    (args.report_dir / f"assistant_golden{suffix}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
