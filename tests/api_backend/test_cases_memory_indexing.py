from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api import memory as memory_module
from backend.app.config import EmbeddingConfig, IndexingConfig, MemoryConfig, SearchConfig, VectorStoreConfig
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity


class _RecordingIndexer:
    """Fake CaseMemoryIndexer that never touches real Qdrant/embeddings."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.indexed_case_ids: list[int] = []
        self.should_fail = should_fail

    def index_case(self, case: OperationalCaseEntity, db: Session):
        self.indexed_case_ids.append(case.id)
        if self.should_fail:
            case.memory_status = "failed"
            case.memory_error = "boom"
            db.commit()
            raise RuntimeError("boom")
        case.memory_status = "indexed"
        case.memory_indexed_at = datetime.utcnow()
        db.commit()


def _memory_config(*, automatic_on_case_creation: bool, automatic_on_case_update: bool) -> MemoryConfig:
    return MemoryConfig(
        enabled=True,
        vector_store=VectorStoreConfig(),
        embedding=EmbeddingConfig(),
        indexing=IndexingConfig(
            automatic_on_case_creation=automatic_on_case_creation,
            automatic_on_case_update=automatic_on_case_update,
        ),
        search=SearchConfig(),
    )


@pytest.fixture
def client_factory():
    created_apps = []

    def _make(*, indexer, config):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[memory_module.get_memory_indexer] = lambda: indexer
        app.dependency_overrides[memory_module.get_memory_config] = lambda: config
        created_apps.append(app)
        return app

    yield _make


def _seed_finding(db: Session, finding_id: int) -> None:
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id="run-memory-indexing",
            service="checkout-api",
            metric_name="cpu_usage",
            title="CPU usage baseline shifted",
            summary="CPU moved from normal baseline to sustained high usage.",
            category="behavior_change",
            health_status="critical",
            importance_score=0.94,
            investigation_priority=1,
            signal_ids=["sig-1"],
            comparison_json={"comparison_type": "selected_window_split"},
            created_at=datetime.utcnow(),
        )
    )
    db.commit()


def test_creating_a_case_auto_indexes_it_when_enabled(client_factory) -> None:
    indexer = _RecordingIndexer()
    config = _memory_config(automatic_on_case_creation=True, automatic_on_case_update=True)
    app = client_factory(indexer=indexer, config=config)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=201)

        response = client.post("/api/cases/findings/201/create")

    assert response.status_code == 200
    body = response.json()
    assert body["memory_status"] == "indexed"
    assert indexer.indexed_case_ids == [body["case_id"]]


def test_creating_a_case_skips_indexing_when_disabled(client_factory) -> None:
    indexer = _RecordingIndexer()
    config = _memory_config(automatic_on_case_creation=False, automatic_on_case_update=True)
    app = client_factory(indexer=indexer, config=config)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=202)

        response = client.post("/api/cases/findings/202/create")

    assert response.status_code == 200
    assert response.json()["memory_status"] == "not_indexed"
    assert indexer.indexed_case_ids == []


def test_indexing_failure_does_not_block_case_creation(client_factory) -> None:
    indexer = _RecordingIndexer(should_fail=True)
    config = _memory_config(automatic_on_case_creation=True, automatic_on_case_update=True)
    app = client_factory(indexer=indexer, config=config)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=203)

        response = client.post("/api/cases/findings/203/create")

    assert response.status_code == 200
    assert response.json()["memory_status"] == "failed"
    assert indexer.indexed_case_ids == [response.json()["case_id"]]


def test_updating_rca_reindexes_an_already_indexed_case_when_auto_update_enabled(client_factory) -> None:
    indexer = _RecordingIndexer()
    config = _memory_config(automatic_on_case_creation=True, automatic_on_case_update=True)
    app = client_factory(indexer=indexer, config=config)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=204)

        case_id = client.post("/api/cases/findings/204/create").json()["case_id"]
        indexer.indexed_case_ids.clear()

        response = client.patch(
            f"/api/cases/{case_id}/rca",
            json={"root_cause_status": "identified", "root_cause_summary": "Deploy caused CPU regression.", "root_cause_verified": True},
        )

    assert response.status_code == 200
    assert response.json()["memory_status"] == "indexed"
    assert indexer.indexed_case_ids == [case_id]


def test_updating_rca_marks_stale_instead_of_reindexing_when_auto_update_disabled(client_factory) -> None:
    indexer = _RecordingIndexer()
    creation_config = _memory_config(automatic_on_case_creation=True, automatic_on_case_update=False)
    app = client_factory(indexer=indexer, config=creation_config)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=205)

        case_id = client.post("/api/cases/findings/205/create").json()["case_id"]
        indexer.indexed_case_ids.clear()

        response = client.patch(
            f"/api/cases/{case_id}/rca",
            json={"root_cause_status": "identified", "root_cause_summary": "Deploy caused CPU regression.", "root_cause_verified": True},
        )

    assert response.status_code == 200
    assert response.json()["memory_status"] == "stale"
    assert indexer.indexed_case_ids == []
