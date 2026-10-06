from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity


class _FakeVectorSearch:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls = 0

    def search(self, vector, limit=5, score_threshold=0.0, filters=None, **_kwargs):
        self.calls += 1
        return self.results


class _FakeIndexer:
    def __init__(self, results: list[dict]) -> None:
        self.collection_name = "fake-collection"
        self.vector_store = _FakeVectorSearch(results)
        self.ensure_indexed_calls = 0

    def ensure_indexed(self, rows, *, id_fn, text_fn, payload_fn) -> None:
        self.ensure_indexed_calls += 1


class _FakeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _FakeDocsStore:
    def search(self, vector, limit=5, score_threshold=0.0, filters=None, **_kwargs):
        return []


_DEFAULT_CASE_SIMILARITY = SimpleNamespace(vector_store=_FakeVectorSearch([]))


def _assistant(*, findings_indexer=None, behaviors_indexer=None, case_similarity=_DEFAULT_CASE_SIMILARITY) -> OperationalIntelligenceAssistant:
    return OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=_FakeEmbedder(),
            case_similarity=case_similarity,
            docs_store=_FakeDocsStore(),
            ai_services=None,
            findings_indexer=findings_indexer,
            behaviors_indexer=behaviors_indexer,
        )
    )


def _seed_finding(db, finding_id: int) -> None:
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id="run-semantic",
            service="checkout-api",
            metric_name="cpu_usage",
            title="CPU usage baseline shifted",
            summary="CPU moved from normal baseline to sustained high usage.",
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


def _seed_behavior(db, behavior_id: int) -> None:
    db.add(
        BehaviorFindingEntity(
            id=behavior_id,
            analysis_run_id="run-semantic",
            service="checkout-api",
            title="Cascading latency and error rate",
            summary="Latency and error rate rose together.",
            category="cascading_failure",
            severity="critical",
            behavior_id="cascading_failure",
            definition_id="cascading_failure_v1",
            evidence_json=[],
            created_at=datetime.utcnow(),
        )
    )
    db.commit()


def _seed_case(db, case_id: int, finding_id: int) -> None:
    db.add(
        OperationalCaseEntity(
            id=case_id,
            finding_id=finding_id,
            analysis_run_id="run-semantic",
            case_title="Checkout CPU regression",
            case_status="resolved",
            finding_snapshot={"service": "checkout-api", "metric_name": "cpu_usage"},
            investigation_status="completed",
            investigation_notes=[],
            root_cause_status="identified",
            root_cause_summary="Deploy raised worker pool size.",
            root_cause_verified=True,
            outcome_status="resolved",
            memory_status="indexed",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()


def test_findings_use_semantic_search_scores_when_indexer_available() -> None:
    indexer = _FakeIndexer([{"score": 0.91, "payload": {"row_id": 402}}])
    assistant = _assistant(findings_indexer=indexer)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=402)

        response = client.post("/api/assistant/chat", json={"message": "unrelated words that share no keywords", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    finding_sources = [source for source in body["sources"] if source["source_type"] == "finding"]
    assert len(finding_sources) == 1
    assert finding_sources[0]["score"] == 0.91
    assert indexer.ensure_indexed_calls == 1


def test_findings_semantic_search_returning_no_matches_does_not_fall_back_to_keyword() -> None:
    indexer = _FakeIndexer([])
    assistant = _assistant(findings_indexer=indexer)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=403)

        # This message would keyword-match "changed" -> FINDING_SEARCH -> _term_score would find the row,
        # but a working semantic search that legitimately found nothing must not be overridden.
        response = client.post("/api/assistant/chat", json={"message": "What changed?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert not any(source["source_type"] == "finding" for source in body["sources"])
    assert indexer.ensure_indexed_calls == 1


def test_findings_fall_back_to_keyword_search_when_no_indexer_is_configured() -> None:
    assistant = _assistant(findings_indexer=None)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=404)

        response = client.post("/api/assistant/chat", json={"message": "What changed in checkout cpu?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert any(source["source_type"] == "finding" for source in body["sources"])


def test_behaviors_use_semantic_search_scores_when_indexer_available() -> None:
    indexer = _FakeIndexer([{"score": 0.77, "payload": {"row_id": 502}}])
    assistant = _assistant(behaviors_indexer=indexer)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_behavior(db, behavior_id=502)

        response = client.post("/api/assistant/chat", json={"message": "How does behavior intelligence explain this?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    behavior_sources = [source for source in body["sources"] if source["source_type"] == "behavior"]
    assert len(behavior_sources) == 1
    assert behavior_sources[0]["score"] == 0.77


def test_cases_use_semantic_search_scores_when_case_similarity_available() -> None:
    case_similarity = SimpleNamespace(vector_store=_FakeVectorSearch([{"score": 0.83, "payload": {"case_id": 601}}]))
    assistant = _assistant(case_similarity=case_similarity)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=601)
            _seed_case(db, case_id=601, finding_id=601)

        response = client.post("/api/assistant/chat", json={"message": "Any cases related to a totally different topic?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    case_sources = [source for source in body["sources"] if source["source_type"] == "case"]
    assert len(case_sources) == 1
    assert case_sources[0]["score"] == 0.83


def test_cases_fall_back_to_keyword_search_when_case_similarity_is_unavailable() -> None:
    # Exercise _search_cases directly - MEMORY_SEARCH always requires case_similarity in
    # this codebase (it's a required field in production), so routing "case" questions
    # through the full chat() flow with case_similarity=None isn't a real scenario. The
    # fallback inside _search_cases itself is still worth covering directly.
    from backend.app.assistant.schemas import AssistantChatRequest

    assistant = _assistant(case_similarity=None)
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app):
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=602)
            _seed_case(db, case_id=602, finding_id=602)

            group = assistant._search_cases(
                AssistantChatRequest(message="Any cases related to checkout regression?", top_k=3),
                db,
            )

    assert any(source.source_type == "case" for source in group.sources)


def test_document_search_score_floor_does_not_exclude_a_genuinely_relevant_short_doc() -> None:
    # Regression test: live-verified gap - "Application Overview" (a real generated doc) scores
    # ~0.38 against a casual question like "whats use of this application" with the real
    # embedding model. The old score_threshold floor (max(0.4, minimum_score)) silently discarded
    # it even when the caller (the real frontend) asked for minimum_score=0.35 - the single most
    # on-topic document in the whole index never had a chance to be returned.
    from backend.app.assistant.schemas import AssistantChatRequest

    class _RecordingDocsStore:
        def __init__(self, results: list[dict]) -> None:
            self.results = results
            self.last_score_threshold: float | None = None

        def search(self, vector, limit=5, score_threshold=0.0, filters=None, **_kwargs):
            self.last_score_threshold = score_threshold
            return [row for row in self.results if row["score"] >= score_threshold]

    docs_store = _RecordingDocsStore(
        [{"score": 0.384, "payload": {"title": "Application Overview", "reference": "", "summary": "...", "source_type": "generated"}}]
    )
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(embedder=_FakeEmbedder(), case_similarity=_DEFAULT_CASE_SIMILARITY, docs_store=docs_store, ai_services=None)
    )

    sources, _ = assistant._answer_application(AssistantChatRequest(message="whats use of this application", top_k=6, minimum_score=0.35))

    assert docs_store.last_score_threshold <= 0.35
    assert any(source.title == "Application Overview" for source in sources)
