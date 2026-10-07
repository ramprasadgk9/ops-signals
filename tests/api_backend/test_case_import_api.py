from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api import memory as memory_module
from backend.app.case_import.service import CaseImportService
from backend.app.case_import.parsers import ImportSettings, parse_files
from backend.app.config import EmbeddingConfig, IndexingConfig, MemoryConfig, SearchConfig, VectorStoreConfig
from backend.app.main import create_app
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalyzerLearningOutcomeEntity, FindingEntity, OperationalCaseEntity

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "case_import"
TEMPLATES = Path(__file__).resolve().parents[2] / "backend" / "app" / "case_import" / "templates"


class _RecordingIndexer:
    """Fake CaseMemoryIndexer: records index and delete calls, never touches Qdrant."""

    def __init__(self) -> None:
        self.indexed_case_ids: list[int] = []
        self.deleted_case_ids: list[int] = []

    def index_case(self, case: OperationalCaseEntity, db: Session):
        self.indexed_case_ids.append(case.id)
        case.memory_status = "indexed"
        case.memory_indexed_at = datetime.utcnow()
        db.commit()

    def delete_memory(self, case: OperationalCaseEntity, db: Session) -> None:
        self.deleted_case_ids.append(case.id)


def _memory_config() -> MemoryConfig:
    return MemoryConfig(
        enabled=True,
        vector_store=VectorStoreConfig(),
        embedding=EmbeddingConfig(),
        indexing=IndexingConfig(automatic_on_case_creation=True, automatic_on_case_update=True),
        search=SearchConfig(),
    )


@pytest.fixture
def indexer() -> _RecordingIndexer:
    return _RecordingIndexer()


@pytest.fixture
def client(indexer: _RecordingIndexer):
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[memory_module.get_memory_indexer] = lambda: indexer
    app.dependency_overrides[memory_module.get_memory_config] = _memory_config
    with TestClient(app) as test_client:
        yield test_client


def _files(*paths: Path) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (path.name, path.read_bytes(), "application/octet-stream")) for path in paths]


def _case_count() -> int:
    with get_session_local()() as db:
        return db.scalar(select(func.count()).select_from(OperationalCaseEntity))


def _cases_by_source_id() -> dict[str, OperationalCaseEntity]:
    with get_session_local()() as db:
        cases = db.execute(select(OperationalCaseEntity)).scalars().all()
        for case in cases:
            db.expunge(case)
        return {case.source_id: case for case in cases}


def test_preview_reports_actions_without_writing(client: TestClient) -> None:
    response = client.post("/api/case-imports/preview", files=_files(FIXTURES / "jira-export.csv"))

    assert response.status_code == 200
    body = response.json()
    assert body["file_profiles"] == {"jira-export.csv": "jira-csv"}
    assert body["counts"] == {"new": 2, "updated": 0, "unchanged": 0, "skipped": 1, "duplicate_rows": 0}
    skipped = [row for row in body["records"] if row["action"] == "skipped"]
    assert skipped[0]["source_id"] == "OPS-420"
    assert skipped[0]["problems"] == ["missing root_cause"]
    assert body["redactions"] == 2
    assert _case_count() == 0


def test_import_creates_resolved_imported_cases_and_indexes_them(
    client: TestClient, indexer: _RecordingIndexer
) -> None:
    response = client.post("/api/case-imports", files=_files(FIXTURES / "jira-export.csv"))

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["new"] == 2
    assert body["indexed"] == 2
    assert body["batch_id"]

    cases = _cases_by_source_id()
    case = cases["OPS-412"]
    assert case.source == "jira"
    assert case.finding_id is None and case.behavior_finding_id is None
    assert case.analysis_run_id == f"import:{body['batch_id']}"
    assert case.case_status == "resolved"
    assert case.outcome_status == "resolved"
    assert case.root_cause_status == "confirmed"
    assert case.finding_snapshot["source_type"] == "imported"
    assert case.finding_snapshot["service"] == "Checkout"
    assert case.created_at == datetime(2025, 3, 14, 18, 20)
    assert sorted(indexer.indexed_case_ids) == sorted(c.id for c in cases.values())

    listed = client.get("/api/cases").json()
    imported = [row for row in listed if row["source_id"] == "OPS-412"][0]
    assert imported["source"] == "jira"
    assert imported["case_status"] == "resolved"


def test_reimporting_the_same_file_creates_no_duplicates(client: TestClient, indexer: _RecordingIndexer) -> None:
    client.post("/api/case-imports", files=_files(FIXTURES / "jira-export.csv"))
    indexed_after_first = len(indexer.indexed_case_ids)

    second = client.post("/api/case-imports", files=_files(FIXTURES / "jira-export.csv")).json()

    assert second["counts"] == {"new": 0, "updated": 0, "unchanged": 2, "skipped": 1, "duplicate_rows": 0}
    assert _case_count() == 2
    assert len(indexer.indexed_case_ids) == indexed_after_first


def test_changed_record_is_updated_in_place_and_reindexed(
    client: TestClient, indexer: _RecordingIndexer
) -> None:
    client.post("/api/case-imports", files=_files(FIXTURES / "jira-export.csv"))
    original = _cases_by_source_id()["OPS-412"]
    indexer.indexed_case_ids.clear()

    edited = (FIXTURES / "jira-export.csv").read_bytes().replace(
        b"made the handler default to off", b"made the handler default to the safe path"
    )
    body = client.post(
        "/api/case-imports", files=[("files", ("jira-export.csv", edited, "text/csv"))]
    ).json()

    assert body["counts"]["updated"] == 1
    assert body["counts"]["unchanged"] == 1
    updated = _cases_by_source_id()["OPS-412"]
    assert updated.id == original.id
    assert "safe path" in updated.corrective_action
    assert indexer.indexed_case_ids == [original.id]


def test_duplicate_rows_in_one_upload_become_one_case(client: TestClient) -> None:
    template = (TEMPLATES / "incident-template.csv").read_bytes()
    body = client.post(
        "/api/case-imports",
        files=[
            ("files", ("a.csv", template, "text/csv")),
            ("files", ("b.csv", template, "text/csv")),
        ],
    ).json()

    assert body["counts"]["new"] == 2
    assert body["counts"]["duplicate_rows"] == 2
    assert _case_count() == 2


def test_notes_added_in_ops_signals_survive_reimport(client: TestClient) -> None:
    client.post("/api/case-imports", files=_files(TEMPLATES / "incident-template.csv"))
    case_id = _cases_by_source_id()["INC-1001"].id
    client.patch(
        f"/api/cases/{case_id}/investigation",
        json={"investigation_status": "completed", "investigation_note": "Same pattern seen in staging"},
    )

    edited = (TEMPLATES / "incident-template.csv").read_bytes().replace(b"lowered max", b"cut max")
    client.post("/api/case-imports", files=[("files", ("incident-template.csv", edited, "text/csv"))])

    notes = _cases_by_source_id()["INC-1001"].investigation_notes
    assert any(note["note"] == "Same pattern seen in staging" for note in notes)
    assert sum(1 for note in notes if note.get("source") == "import") == 1


def test_markdown_without_id_reimports_as_unchanged(client: TestClient) -> None:
    text = (
        b"---\ntitle: Disk full\nservice: metrics-store\nstarted_at: 2025-02-01T10:00:00Z\n---\n\n"
        b"## Root cause\n\nRetention job stopped.\n"
    )
    first = client.post("/api/case-imports", files=[("files", ("disk.md", text, "text/markdown"))]).json()
    second = client.post("/api/case-imports", files=[("files", ("disk.md", text, "text/markdown"))]).json()

    assert first["counts"]["new"] == 1
    assert second["counts"]["unchanged"] == 1
    assert _case_count() == 1


def test_concurrent_insert_of_same_record_updates_instead_of_duplicating(client: TestClient) -> None:
    """Simulates a second import committing the same record between this import's plan and
    write: the unique (source, source_id) index rejects the insert and the service retries
    it as an update."""
    parsed = parse_files([((TEMPLATES / "incident-template.csv").name, (TEMPLATES / "incident-template.csv").read_bytes())], ImportSettings())
    session_local = get_session_local()
    with session_local() as db:
        service = CaseImportService(db)
        plan = service.plan(parsed)
        with session_local() as other:
            CaseImportService(other).apply(service.plan(parsed), source_files=["other.csv"])
        result = service.apply(plan, source_files=["incident-template.csv"])

    assert result.counts["new"] == 0
    assert result.counts["unchanged"] + result.counts["updated"] == 2
    assert _case_count() == 2


def test_undo_removes_cases_created_by_the_batch(client: TestClient, indexer: _RecordingIndexer) -> None:
    first = client.post("/api/case-imports", files=_files(FIXTURES / "pagerduty-export.csv")).json()
    client.post("/api/case-imports", files=_files(FIXTURES / "jira-export.csv"))

    batches = client.get("/api/case-imports").json()
    assert [batch["id"] for batch in batches][-1] == first["batch_id"]

    response = client.delete(f"/api/case-imports/{first['batch_id']}")

    assert response.status_code == 200
    assert response.json()["deleted_cases"] == 2
    assert set(_cases_by_source_id()) == {"OPS-412", "OPS-415"}
    assert len(indexer.deleted_case_ids) == 2
    assert client.get("/api/case-imports").json()[0]["status"] == "completed"
    assert [b for b in client.get("/api/case-imports").json() if b["id"] == first["batch_id"]][0]["status"] == "undone"


def test_settings_json_applies_aliases(client: TestClient) -> None:
    body = client.post(
        "/api/case-imports",
        files=_files(FIXTURES / "jira-export.csv"),
        data={"settings": json.dumps({"service_aliases": {"Checkout": "checkout-api"}})},
    ).json()

    assert body["counts"]["new"] == 2
    assert _cases_by_source_id()["OPS-412"].finding_snapshot["service"] == "checkout-api"


def test_invalid_settings_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/case-imports/preview",
        files=_files(FIXTURES / "jira-export.csv"),
        data={"settings": "{not json"},
    )
    assert response.status_code == 400


def test_resolving_an_imported_case_needs_no_learning_outcome(client: TestClient) -> None:
    client.post("/api/case-imports", files=_files(TEMPLATES / "incident-template.csv"))
    case_id = _cases_by_source_id()["INC-1001"].id

    response = client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "resolved", "outcome_summary": "Still fine", "corrective_action": "Pool alert"},
    )

    assert response.status_code == 200
    with get_session_local()() as db:
        assert db.scalar(select(func.count()).select_from(AnalyzerLearningOutcomeEntity)) == 0


def test_resolving_imported_case_ignores_learning_outcome_if_sent(client: TestClient) -> None:
    client.post("/api/case-imports", files=_files(TEMPLATES / "incident-template.csv"))
    case_id = _cases_by_source_id()["INC-1001"].id

    response = client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "resolved", "learning_outcome_status": "confirmed"},
    )

    assert response.status_code == 200
    with get_session_local()() as db:
        assert db.scalar(select(func.count()).select_from(AnalyzerLearningOutcomeEntity)) == 0


def test_detected_cases_still_require_exactly_one_finding_link(client: TestClient) -> None:
    from sqlalchemy.exc import IntegrityError

    with get_session_local()() as db:
        db.add(
            OperationalCaseEntity(
                analysis_run_id="run-x",
                case_title="orphan",
                finding_snapshot={},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_overview_counts_are_unaffected_by_imported_cases(client: TestClient) -> None:
    with get_session_local()() as db:
        db.add(
            FindingEntity(
                id=1,
                analysis_run_id="run-1",
                service="checkout-api",
                metric_name="latency",
                title="Latency up",
                summary="Latency up",
                category="behavior_change",
                health_status="critical",
                importance_score=0.9,
                investigation_priority=1,
                signal_ids=[],
                comparison_json={},
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    before = client.get("/api/overview/summary").json()
    client.post("/api/case-imports", files=_files(TEMPLATES / "incident-template.csv"))
    after = client.get("/api/overview/summary").json()

    assert after["active_findings"] == before["active_findings"]
    assert after["open_cases"] == before["open_cases"]


def test_profiles_and_templates_are_served(client: TestClient) -> None:
    profiles = client.get("/api/case-imports/profiles").json()
    assert {profile["id"] for profile in profiles["profiles"]} == {
        "markdown",
        "generic-csv",
        "jira-csv",
        "pagerduty-csv",
    }
    assert "root_cause" in profiles["required_fields"]

    template = client.get("/api/case-imports/templates/incident-template.csv")
    assert template.status_code == 200
    assert template.text.startswith("id,title,service")
    assert client.get("/api/case-imports/templates/../../main.py").status_code == 404


def test_document_and_payload_mark_imported_cases() -> None:
    parsed = parse_files([((TEMPLATES / "example-postmortem.md").name, (TEMPLATES / "example-postmortem.md").read_bytes())], ImportSettings())
    case = CaseImportService.build_case(parsed.records[0], batch_id="b1")
    case.id = 7

    document = CaseDocumentBuilder.build(case)
    assert "Imported Incident (postmortems PM-2025-007)" in document
    assert "Service: search-api" in document
    assert "Metric:" not in document
    assert "The nightly index rebuild" in document

    payload = CaseMemoryIndexer._build_payload(case, [])
    assert payload["origin"] == "imported"
    assert payload["source"] == "postmortems"
    assert payload["service"] == "search-api"


def test_seen_before_for_unknown_finding_is_404(client: TestClient) -> None:
    assert client.get("/api/findings/999/seen-before").status_code == 404


def test_seen_before_says_why_when_memory_is_off() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[memory_module.get_memory_config] = lambda: MemoryConfig(enabled=False)
    with TestClient(app) as client:
        with get_session_local()() as db:
            db.add(
                FindingEntity(
                    id=5, analysis_run_id="run-5", service="checkout", metric_name="cpu_usage", title="CPU up",
                    summary="CPU up", category="baseline_shift", health_status="critical", importance_score=0.9,
                    investigation_priority=1, signal_ids=[], comparison_json={}, created_at=datetime.utcnow(),
                )
            )
            db.commit()
        body = client.get("/api/findings/5/seen-before").json()

    assert body["available"] is False
    assert "not enabled" in body["reason"]
    assert body["matches"] == []
