"""The Docs check page's backend: coverage, drafted questions, ask-and-grade, and saving tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.models import StructuredLLMService
from backend.app.assistant.docs_check import DocsCheckService, EvaluateRequest, GoldenSetError, NewTest, SaveTestsRequest
from backend.app.assistant.golden import GOLDEN_RELATIVE_PATH, load_golden
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.assistant.schemas import AssistantChatRequest, AssistantChatResponse, AssistantEvidenceGroup, AssistantSource

FEATURE = """# Feature flags

Flags turn features on and off.

## Enabling a flag

Set `OPS_SIGNALS_FEATURE_X=true` and restart the backend.

## Scope

A flag can be limited with `service: checkout-api`.

## History

Flags were added in 0.3.0.
"""

GOLDEN = """questions:
  - id: existing-flag
    category: docs
    question: how do i enable a flag
    contains: ["OPS_SIGNALS_FEATURE_X"]
    expect:
      - {source: docs/flags.md, section: "Enabling a flag"}
"""


class _Embedder:
    model_name = "fake"

    def encode(self, text: str) -> list[float]:
        return [0.1] * ApplicationKnowledgeBootstrapService.VECTOR_SIZE


def _repo(tmp_path: Path, golden: bool = True) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "flags.md").write_text(FEATURE, encoding="utf-8")
    if golden:
        (tmp_path / GOLDEN_RELATIVE_PATH).parent.mkdir(parents=True)
        (tmp_path / GOLDEN_RELATIVE_PATH).write_text(GOLDEN, encoding="utf-8")
    return tmp_path


def _service(repo: Path, assistant=None, ai_services=None, bootstrapped: bool = True) -> DocsCheckService:
    bootstrap = ApplicationKnowledgeBootstrapService(client=QdrantClient(":memory:"), embedder=_Embedder(), repo_root=repo)
    if bootstrapped:
        bootstrap.bootstrap()
    return DocsCheckService(bootstrap=bootstrap, assistant=assistant, ai_services=ai_services, repo_root=repo)


def _flags_coverage(service: DocsCheckService):
    return next(doc for doc in service.coverage().docs if doc.source_path == "docs/flags.md")


# --- coverage -------------------------------------------------------------------------------------


def test_coverage_counts_tests_per_doc_and_lists_untested_sections(tmp_path: Path) -> None:
    flags = _flags_coverage(_service(_repo(tmp_path)))

    assert flags.title == "Feature flags"
    assert (flags.section_count, flags.test_count) == (3, 1)
    assert flags.untested_sections == ["Scope", "History"]
    assert flags.recently == "added"


def test_coverage_says_when_this_server_has_no_golden_file(tmp_path: Path) -> None:
    coverage = _service(_repo(tmp_path, golden=False)).coverage()

    assert coverage.golden_available is False
    assert coverage.covered_docs == 0


# --- drafting ---------------------------------------------------------------------------------------


def test_without_ai_questions_are_drafted_from_untested_headings(tmp_path: Path) -> None:
    drafts = _service(_repo(tmp_path)).draft_questions("docs/flags.md")

    assert [(draft.section, draft.contains, draft.drafted_by) for draft in drafts] == [
        ("Scope", ["service: checkout-api"], "headings"),
        ("History", [], "headings"),
    ]
    assert drafts[0].question == "What should I know about scope in Feature flags?"


class _ScriptedClient(LLMClient):
    model = "gemma3:4b"

    def __init__(self, content: str) -> None:
        self.content = content

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self.content, model=self.model, provider="fake")


def test_llm_drafts_keep_only_real_sections_and_phrases_copied_from_them(tmp_path: Path) -> None:
    client = _ScriptedClient(
        '{"questions": ['
        '{"section": "Scope", "question": "can i limit a flag to one service", "phrase": "service: checkout-api"},'
        '{"section": "History", "question": "when did flags arrive", "phrase": "released in 2019"},'
        '{"section": "Pricing", "question": "how much do flags cost", "phrase": "free"}'
        "]}"
    )
    ai = OptionalAIServices(client=client, structured=StructuredLLMService(client))

    drafts = _service(_repo(tmp_path), ai_services=ai).draft_questions("docs/flags.md")

    assert [(draft.section, draft.question, draft.contains, draft.drafted_by) for draft in drafts] == [
        ("Scope", "can i limit a flag to one service", ["service: checkout-api"], "gemma3:4b"),
        ("History", "when did flags arrive", [], "gemma3:4b"),
    ]


def test_drafting_an_unknown_doc_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(GoldenSetError):
        _service(_repo(tmp_path)).draft_questions("docs/nope.md")


# --- evaluating -------------------------------------------------------------------------------------


class _Assistant:
    def __init__(self, sources: list[AssistantSource]) -> None:
        self.sources = sources
        self.services = SimpleNamespace(ai_services=None)

    def chat(self, payload: AssistantChatRequest, db) -> AssistantChatResponse:
        group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=len(self.sources), sources=self.sources)
        return AssistantChatResponse(conversation_id="00000000-0000-0000-0000-000000000000", intent="documentation", answer="answer", limitations=[], suggested_questions=[], sources=self.sources, evidence_groups=[group])


def _doc_source(path: str, section: str) -> AssistantSource:
    return AssistantSource(source_type="app_documentation", title="t", score=0.5, reference=f"{path}#x", source_path=path, section=section, quote="q")


def test_evaluate_reports_where_the_expected_section_ranked(tmp_path: Path) -> None:
    assistant = _Assistant([_doc_source("README.md", "6.1 Prerequisites"), _doc_source("docs/flags.md", "Scope")])
    service = _service(_repo(tmp_path), assistant=assistant)

    hit = service.evaluate(EvaluateRequest(question="limit a flag", source_path="docs/flags.md", section="Scope"), db=None)
    miss = service.evaluate(EvaluateRequest(question="limit a flag", source_path="docs/flags.md", section="History"), db=None)

    assert (hit.cited_expected, hit.rank) == (True, 2)
    assert (miss.cited_expected, miss.rank) == (False, None)
    assert [cited.section for cited in hit.cited] == ["6.1 Prerequisites", "Scope"]


# --- saving -----------------------------------------------------------------------------------------


def test_a_dry_run_returns_the_yaml_without_writing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    request = SaveTestsRequest(tests=[NewTest(question="can i limit a flag", source_path="docs/flags.md", section="Scope", contains=["service: checkout-api"])], dry_run=True)

    result = _service(repo).save_tests(request, db=None)

    assert result.written is False and result.saved_ids == ["flags-scope"]
    assert '- {source: "docs/flags.md", section: "Scope"}' in result.yaml
    assert (repo / GOLDEN_RELATIVE_PATH).read_text(encoding="utf-8") == GOLDEN


def test_saved_tests_are_appended_and_the_file_still_parses(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    request = SaveTestsRequest(
        tests=[
            NewTest(question='what\'s "scope"?', source_path="docs/flags.md", section="Scope", contains=["service: checkout-api"]),
            NewTest(question="when were flags added", source_path="docs/flags.md", section="History", contains=["0.3.0"], known_gap=True),
        ]
    )

    result = _service(repo).save_tests(request, db=None)
    questions = {question.id: question for question in load_golden(repo / GOLDEN_RELATIVE_PATH)}

    assert result.written is True
    assert questions["flags-scope"].question == 'what\'s "scope"?'
    assert questions["flags-history"].category == "known_gap"
    assert "existing-flag" in questions


def test_a_test_whose_phrase_is_not_in_its_section_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    request = SaveTestsRequest(tests=[NewTest(question="scope", source_path="docs/flags.md", section="Scope", contains=["OPS_SIGNALS_FEATURE_X"])])

    with pytest.raises(GoldenSetError, match="does not contain"):
        _service(repo).save_tests(request, db=None)
    assert (repo / GOLDEN_RELATIVE_PATH).read_text(encoding="utf-8") == GOLDEN


def test_ids_stay_unique(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    test = NewTest(question="how do i enable a flag", source_path="docs/flags.md", section="Enabling a flag")

    result = _service(repo).save_tests(SaveTestsRequest(tests=[test, test]), db=None)

    assert result.saved_ids == ["flags-enabling-flag", "flags-enabling-flag-2"]
    assert len({question.id for question in load_golden(repo / GOLDEN_RELATIVE_PATH)}) == 3


# --- API --------------------------------------------------------------------------------------------


def test_saving_needs_file_writes_but_a_dry_run_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api import assistant as assistant_module
    from backend.app.main import create_app

    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_ALLOW_FILE_WRITES", "false")
    repo = _repo(tmp_path)
    service = _service(repo)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_docs_check] = lambda: service
    body = {"tests": [{"question": "can i limit a flag", "source_path": "docs/flags.md", "section": "Scope", "contains": ["service: checkout-api"]}]}

    with TestClient(app) as client:
        refused = client.post("/api/assistant/docs-check/tests", json=body)
        preview = client.post("/api/assistant/docs-check/tests", json={**body, "dry_run": True})
        invalid = client.post("/api/assistant/docs-check/tests", json={"tests": [{**body["tests"][0], "contains": ["nope"]}], "dry_run": True})
        coverage = client.get("/api/assistant/docs-check/coverage")

    assert refused.status_code == 403
    assert preview.status_code == 200 and preview.json()["written"] is False
    assert invalid.status_code == 422 and "does not contain" in invalid.json()["detail"]
    assert coverage.status_code == 200 and coverage.json()["golden_available"] is True
    assert yaml.safe_load((repo / GOLDEN_RELATIVE_PATH).read_text(encoding="utf-8"))["questions"][-1]["id"] == "existing-flag"


def test_llm_drafts_keep_one_question_per_section(tmp_path: Path) -> None:
    client = _ScriptedClient(
        '{"questions": ['
        '{"section": "Scope", "question": "limit a flag", "phrase": ""},'
        '{"section": "Scope", "question": "limit it again", "phrase": ""}'
        "]}"
    )
    ai = OptionalAIServices(client=client, structured=StructuredLLMService(client))

    drafts = _service(_repo(tmp_path), ai_services=ai).draft_questions("docs/flags.md")

    assert [draft.question for draft in drafts] == ["limit a flag"]
