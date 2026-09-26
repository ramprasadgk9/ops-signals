"""The Ask Ops Signals golden question set: known-answer questions about the documentation.

Each question names where its answer lives (a knowledge document's source_path and, for Markdown,
a section heading) and phrases the answering passage must contain. The benchmark scores the
assistant against it; the Docs check page adds questions to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeDocument
from backend.app.assistant.markdown_sections import split_sections

# Relative to the repository root.
GOLDEN_RELATIVE_PATH = Path("benchmark") / "assistant" / "golden_questions.yml"
GOLDEN_PATH = Path(__file__).resolve().parents[3] / GOLDEN_RELATIVE_PATH

# Reported, never scored. out_of_scope: nothing in the docs answers it. known_gap: the docs answer
# it but the assistant doesn't yet - saved from the Docs check page so the gap is recorded without
# failing the build; the benchmark says when one starts passing.
UNSCORED_CATEGORIES = frozenset({"out_of_scope", "known_gap"})


@dataclass(slots=True)
class Expectation:
    source: str
    section: str | None = None


@dataclass(slots=True)
class GoldenQuestion:
    id: str
    category: str
    question: str
    contains: list[str] = field(default_factory=list)
    expect: list[Expectation] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.category not in UNSCORED_CATEGORIES


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    return [
        GoldenQuestion(
            id=item["id"],
            category=item["category"],
            question=item["question"],
            contains=list(item.get("contains", [])),
            expect=[Expectation(source=exp["source"], section=exp.get("section")) for exp in item.get("expect", [])],
        )
        for item in raw
    ]


def contains_all(text: str, phrases: list[str]) -> bool:
    lowered = text.lower()
    return all(phrase.lower() in lowered for phrase in phrases)


def section_text(document: ApplicationKnowledgeDocument, section: str) -> str | None:
    """Text of the section whose heading path contains `section`, including its subsections."""
    sections = split_sections(document.content)
    for index, candidate in enumerate(sections):
        if section.lower() not in candidate.breadcrumb.lower():
            continue
        parts = [candidate.text]
        for following in sections[index + 1 :]:
            if following.level <= candidate.level:
                break
            parts.append(following.text)
        return "\n".join(parts)
    return None


def validate_golden(questions: list[GoldenQuestion], documents: list[ApplicationKnowledgeDocument]) -> list[str]:
    """Every problem with the golden set against the current corpus: duplicate ids, an expected
    source or section that doesn't exist, or one that doesn't contain the expected phrases."""
    by_path = {document.source_path: document for document in documents}
    errors: list[str] = []
    seen: set[str] = set()
    for question in questions:
        if question.id in seen:
            errors.append(f"{question.id}: duplicate id")
        seen.add(question.id)
        if question.scored and not question.expect:
            errors.append(f"{question.id}: scored question has no expectations")
        for expectation in question.expect:
            document = by_path.get(expectation.source)
            if document is None:
                errors.append(f"{question.id}: no knowledge document with source_path {expectation.source!r}")
                continue
            text = document.content if expectation.section is None else section_text(document, expectation.section)
            if text is None:
                errors.append(f"{question.id}: {expectation.source} has no section matching {expectation.section!r}")
            elif not contains_all(text, question.contains):
                where = expectation.source + (f" > {expectation.section}" if expectation.section else "")
                errors.append(f"{question.id}: {where} does not contain all of {question.contains}")
    return errors
