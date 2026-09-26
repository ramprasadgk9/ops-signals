"""The Docs check page's backend: which docs have no golden questions, drafted questions for a
doc, whether the assistant answers one from the expected section, and saving approved questions
to the golden set.

Everything here reads; only save_tests() writes, and only to the golden question file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.assistant import feedback
from backend.app.assistant.golden import GOLDEN_RELATIVE_PATH, Expectation, GoldenQuestion, load_golden, validate_golden
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService, ApplicationKnowledgeDocument
from backend.app.assistant.markdown_sections import MarkdownSection, split_sections
from backend.app.assistant.passages import quote_is_in
from backend.app.assistant.schemas import AssistantChatRequest
from backend.app.assistant.service import OperationalIntelligenceAssistant

logger = logging.getLogger(__name__)

# How much of each section the drafting prompt carries (one section per requested question).
DRAFT_SECTION_CHARS = 700
# A must-contain phrase longer than this is a sentence, not a phrase.
MAX_PHRASE_CHARS = 80
_CODE_SPAN = re.compile(r"`([^`\n]{2,60})`")


# --- API models ------------------------------------------------------------------------------------


class DocCoverage(BaseModel):
    source_path: str
    title: str
    section_count: int
    test_count: int
    untested_sections: list[str] = Field(default_factory=list)
    # "added" or "changed" when the last reindex in this process touched it.
    recently: str | None = None


class DocsCoverage(BaseModel):
    # False when this server has no golden question file (a packaged install).
    golden_available: bool
    total_docs: int
    covered_docs: int
    docs: list[DocCoverage] = Field(default_factory=list)


class DraftQuestion(BaseModel):
    source_path: str
    section: str
    question: str
    contains: list[str] = Field(default_factory=list)
    # The model that drafted it, or "headings" when drafted without AI.
    drafted_by: str


class EvaluateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    source_path: str
    section: str | None = None


class CitedSection(BaseModel):
    source_path: str | None = None
    section: str | None = None
    reference: str = ""
    quote: str | None = None


class EvaluateResult(BaseModel):
    cited_expected: bool
    # 1-3 when the expected section is among the first three documentation sources.
    rank: int | None = None
    cited: list[CitedSection] = Field(default_factory=list)
    answer: str
    ai_synthesis_used: bool = False


class NewTest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    source_path: str
    section: str | None = None
    contains: list[str] = Field(default_factory=list, max_length=5)
    # A question the assistant gets wrong today is saved as a known gap: recorded, not scored.
    known_gap: bool = False
    # Thumbs-down feedback this question came from; marked added_as_test once saved.
    feedback_ids: list[int] = Field(default_factory=list)


class SaveTestsRequest(BaseModel):
    tests: list[NewTest] = Field(min_length=1, max_length=50)
    dry_run: bool = False


class SaveTestsResult(BaseModel):
    saved_ids: list[str] = Field(default_factory=list)
    yaml: str
    path: str
    written: bool


class GoldenSetError(Exception):
    """The request can't be saved; the message says why."""


class _Drafted(BaseModel):
    section: str
    question: str
    phrase: str = ""


class _DraftedList(BaseModel):
    questions: list[_Drafted] = Field(default_factory=list)


# --- Service ---------------------------------------------------------------------------------------


@dataclass
class DocsCheckService:
    bootstrap: ApplicationKnowledgeBootstrapService
    assistant: OperationalIntelligenceAssistant | None
    ai_services: OptionalAIServices | None
    repo_root: Path

    @property
    def golden_path(self) -> Path:
        return self.repo_root / GOLDEN_RELATIVE_PATH

    def coverage(self) -> DocsCoverage:
        documents = self._authored_documents()
        golden = self._golden()
        recent: dict[str, str] = {}
        if self.bootstrap.last_result:
            recent.update({path: "changed" for path in self.bootstrap.last_result.changed})
            recent.update({path: "added" for path in self.bootstrap.last_result.added})
        docs: list[DocCoverage] = []
        for document in documents:
            sections = _answerable_sections(document)
            expectations = [(question, expectation) for question in golden for expectation in question.expect if expectation.source == document.source_path]
            tested = {
                section.breadcrumb
                for section in sections
                for _, expectation in expectations
                if expectation.section is None or expectation.section.lower() in section.breadcrumb.lower()
            }
            docs.append(
                DocCoverage(
                    source_path=document.source_path,
                    title=document.title,
                    section_count=len(sections),
                    test_count=len({question.id for question, _ in expectations}),
                    untested_sections=[_label(section, document.title) for section in sections if section.breadcrumb not in tested],
                    recently=recent.get(document.source_path),
                )
            )
        # Just-reindexed docs first, then untested ones, then the rest by path.
        docs.sort(key=lambda doc: (doc.recently is None, doc.test_count > 0, doc.source_path))
        return DocsCoverage(
            golden_available=self.golden_path.exists(),
            total_docs=len(docs),
            covered_docs=sum(1 for doc in docs if doc.test_count),
            docs=docs,
        )

    def draft_questions(self, source_path: str, limit: int = 5) -> list[DraftQuestion]:
        document = self._document(source_path)
        untested = {label for doc in self.coverage().docs if doc.source_path == source_path for label in doc.untested_sections}
        # Untested sections first; a fully tested doc still gets drafts from all its sections.
        sections = [section for section in _answerable_sections(document) if _label(section, document.title) in untested] or _answerable_sections(document)
        sections = sections[: max(limit, 1)]
        drafted = self._draft_with_llm(document, sections, limit) if self.ai_services else []
        return drafted or _draft_from_headings(document, sections, limit)

    def evaluate(self, request: EvaluateRequest, db: Session) -> EvaluateResult:
        if self.assistant is None:
            raise GoldenSetError("The assistant is not initialized, so questions can't be asked.")
        response = self.assistant.chat(AssistantChatRequest(message=request.question, top_k=6, minimum_score=0.35), db)
        docs = [group for group in response.evidence_groups if group.source_type == "app_documentation"]
        leading = docs[0].sources[:3] if docs else []
        rank = next(
            (
                index + 1
                for index, source in enumerate(leading)
                if source.source_path == request.source_path
                and (not request.section or request.section.lower() in (source.section or "").lower())
            ),
            None,
        )
        return EvaluateResult(
            cited_expected=rank is not None,
            rank=rank,
            cited=[CitedSection(source_path=source.source_path, section=source.section, reference=source.reference, quote=source.quote) for source in leading],
            answer=response.answer,
            ai_synthesis_used=response.ai_synthesis_used,
        )

    def save_tests(self, request: SaveTestsRequest, db: Session) -> SaveTestsResult:
        """Appends the tests to the golden question file after checking each against the docs the
        way test_assistant_golden will. dry_run returns the YAML without writing it."""
        path = self.golden_path
        if not path.exists():
            raise GoldenSetError(f"No golden question file at {GOLDEN_RELATIVE_PATH} on this server. Save tests from a local checkout.")
        existing = load_golden(path)
        taken = {question.id for question in existing}
        new_questions: list[GoldenQuestion] = []
        for test in request.tests:
            question_id = _unique_id(test.source_path, test.question, taken)
            taken.add(question_id)
            new_questions.append(
                GoldenQuestion(
                    id=question_id,
                    category="known_gap" if test.known_gap else "docs",
                    question=test.question.strip(),
                    contains=[phrase.strip() for phrase in test.contains if phrase.strip()],
                    expect=[Expectation(source=test.source_path, section=test.section or None)],
                )
            )
        errors = validate_golden(new_questions, self.bootstrap._build_documents())
        if errors:
            raise GoldenSetError("; ".join(errors))
        block = render_yaml(new_questions)
        if request.dry_run:
            return SaveTestsResult(saved_ids=[question.id for question in new_questions], yaml=block, path=str(GOLDEN_RELATIVE_PATH), written=False)

        original = path.read_text(encoding="utf-8")
        path.write_text(original.rstrip("\n") + "\n\n" + block, encoding="utf-8")
        try:
            load_golden(path)
        except Exception as exc:
            path.write_text(original, encoding="utf-8")
            raise GoldenSetError(f"The golden file would no longer parse, nothing was saved: {exc}") from exc
        feedback.set_status(db, [feedback_id for test in request.tests for feedback_id in test.feedback_ids], "added_as_test")
        return SaveTestsResult(saved_ids=[question.id for question in new_questions], yaml=block, path=str(GOLDEN_RELATIVE_PATH), written=True)

    # --- helpers ---

    def _authored_documents(self) -> list[ApplicationKnowledgeDocument]:
        # Generated concept and analyzer docs are rebuilt from code; only repo docs are written by people.
        return [document for document in self.bootstrap._build_documents() if document.source_type == "repo"]

    def _document(self, source_path: str) -> ApplicationKnowledgeDocument:
        for document in self._authored_documents():
            if document.source_path == source_path:
                return document
        raise GoldenSetError(f"No indexed doc at {source_path}.")

    def _golden(self) -> list[GoldenQuestion]:
        try:
            return load_golden(self.golden_path) if self.golden_path.exists() else []
        except Exception as exc:
            logger.warning("Could not read the golden question file: %s", exc)
            return []

    def _draft_with_llm(self, document: ApplicationKnowledgeDocument, sections: list[MarkdownSection], limit: int) -> list[DraftQuestion]:
        evidence = "\n\n".join(f"### {_label(section, document.title)}\n{_body(section)[:DRAFT_SECTION_CHARS]}" for section in sections)
        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "You write test questions for a documentation assistant. For the sections below, write "
                        "ONE question per section - a question a real user would type, informal and short (e.g. "
                        "'how do i turn on auth') - that only that section answers. Do not copy the section's wording into "
                        "the question. For each, give the section's heading exactly as written after '###', and a "
                        "short phrase (a command, setting name, value or 2-6 word fragment) copied character for "
                        "character from that section that a correct answer must contain. Reply with JSON only: "
                        '{"questions": [{"section": "...", "question": "...", "phrase": "..."}]}'
                    ),
                ),
                LLMMessage(role="user", content=f"Document: {document.title}\n\n{evidence}"),
            ],
            temperature=0.3,
            max_tokens=700,
            response_format="json",
            timeout_seconds=45,
        )
        try:
            drafted = self.ai_services.structured.generate_structured(request, _DraftedList)
        except (AIError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Drafting questions with the LLM failed, drafting from headings instead: %s", exc)
            return []
        by_label = {_label(section, document.title).lower(): section for section in sections}
        model = getattr(self.ai_services.client, "model", None) or "AI"
        questions: list[DraftQuestion] = []
        used: set[str] = set()
        for item in drafted.questions:
            section = by_label.get(item.section.strip().lower()) or next(
                (candidate for label, candidate in by_label.items() if item.section.strip().lower() in label), None
            )
            # One per section: a small model tends to pile every question onto one section.
            if section is None or not item.question.strip() or section.breadcrumb in used:
                continue
            used.add(section.breadcrumb)
            phrase = item.phrase.strip().strip("`")
            # A phrase the model made up, or a whole sentence, would make the test check the wrong thing.
            contains = [phrase] if phrase and len(phrase) <= MAX_PHRASE_CHARS and quote_is_in(phrase, _body(section)) else []
            questions.append(DraftQuestion(source_path=document.source_path, section=_label(section, document.title), question=item.question.strip(), contains=contains, drafted_by=model))
            if len(questions) >= limit:
                break
        return questions


# --- module helpers ----------------------------------------------------------------------------------


def _answerable_sections(document: ApplicationKnowledgeDocument) -> list[MarkdownSection]:
    """Sections under the document's title that have text of their own."""
    return [section for section in split_sections(document.content) if section.level >= 2 and _body(section)]


def _body(section: MarkdownSection) -> str:
    return section.text.split("\n", 1)[1].strip() if "\n" in section.text else ""


def _label(section: MarkdownSection, title: str) -> str:
    """The heading path below the document's own title - what golden expectations match against."""
    path = section.heading_path[1:] if len(section.heading_path) > 1 and section.heading_path[0] == title else section.heading_path
    return " > ".join(path)


def _draft_from_headings(document: ApplicationKnowledgeDocument, sections: list[MarkdownSection], limit: int) -> list[DraftQuestion]:
    """Without AI: a plain question per section from its heading, and its first code span as the
    phrase. Stiffer than real users' wording - edit them before saving."""
    drafts: list[DraftQuestion] = []
    for section in sections[:limit]:
        heading = re.sub(r"^[\d.]+\s+", "", section.heading).strip().rstrip(":")
        question = heading if heading.endswith("?") else f"{document.title}: what about {heading[0].lower() + heading[1:]}?"
        code = _CODE_SPAN.search(_body(section))
        drafts.append(DraftQuestion(source_path=document.source_path, section=_label(section, document.title), question=question, contains=[code.group(1)] if code else [], drafted_by="headings"))
    return drafts


def _unique_id(source_path: str, question: str, taken: set[str]) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(source_path).stem.lower()).strip("-")
    words = [word for word in re.findall(r"[a-z0-9]+", question.lower()) if len(word) > 2][:4]
    base = "-".join([stem, *words])[:60].strip("-") or "question"
    candidate, suffix = base, 2
    while candidate in taken:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def render_yaml(questions: list[GoldenQuestion]) -> str:
    """The questions in the golden file's own layout. Strings are JSON-quoted, which YAML reads
    as double-quoted scalars, so any question text round-trips."""
    lines: list[str] = []
    for question in questions:
        lines.extend([
            f"  - id: {question.id}",
            f"    category: {question.category}",
            f"    question: {json.dumps(question.question)}",
            f"    contains: {json.dumps(question.contains)}",
            "    expect:",
        ])
        for expectation in question.expect:
            section = f", section: {json.dumps(expectation.section)}" if expectation.section else ""
            lines.append(f"      - {{source: {json.dumps(expectation.source)}{section}}}")
        lines.append("")
    return "\n".join(lines)
