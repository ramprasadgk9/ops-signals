from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.api import assistant as assistant_module
from backend.app.api import memory as memory_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.memory.schemas import SimilarCaseMatch, SimilarCasesResponse
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity


class _ScriptedClient:
    def __init__(self, *, response_text: str | None = None, raise_error: bool = False) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.raise_error:
            raise AIError("boom")
        return LLMResponse(content=self.response_text or "")


def _assistant_with(client: _ScriptedClient) -> OperationalIntelligenceAssistant:
    services = AssistantServices(
        embedder=None,
        case_similarity=None,
        docs_store=None,
        ai_services=OptionalAIServices(client=client, structured=None),
    )
    return OperationalIntelligenceAssistant(services)


class _FakeSimilarityService:
    def __init__(self, matches: list[SimilarCaseMatch]) -> None:
        self.matches = matches

    def find_similar_cases(self, case_id: int, db: Session, top_k: int | None = None, **_kwargs) -> SimilarCasesResponse:
        return SimilarCasesResponse(source_case_id=case_id, matches=self.matches)


@pytest.fixture
def client_factory():
    created_apps = []

    def _make(*, assistant=None, similarity_service=None):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant
        app.dependency_overrides[memory_module.get_similarity_service] = lambda: similarity_service
        created_apps.append(app)
        return app

    yield _make


def _seed_case(case_id: int, finding_id: int, *, notes: list[dict] | None = None, root_cause_summary: str | None = None, corrective_action: str | None = None) -> None:
    session_local = get_session_local()
    with session_local() as db:
        db.add(
            FindingEntity(
                id=finding_id,
                analysis_run_id="run-ai-drafts",
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
        db.add(
            OperationalCaseEntity(
                id=case_id,
                finding_id=finding_id,
                analysis_run_id="run-ai-drafts",
                case_title="CPU usage baseline shifted",
                case_status="open",
                finding_snapshot={
                    "id": finding_id,
                    "service": "checkout-api",
                    "metric_name": "cpu_usage",
                    "title": "CPU usage baseline shifted",
                    "summary": "CPU moved from normal baseline to sustained high usage.",
                    "category": "behavior_change",
                },
                investigation_status="not_started",
                investigation_notes=notes or [],
                root_cause_status="unknown",
                root_cause_summary=root_cause_summary,
                root_cause_verified=False,
                corrective_action=corrective_action,
                outcome_status="pending",
                memory_status="not_indexed",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        db.commit()


# --- RCA draft suggestion -----------------------------------------------------------------


def test_rca_suggest_unavailable_when_assistant_is_missing(client_factory) -> None:
    app = client_factory(assistant=None, similarity_service=None)

    with TestClient(app) as client:
        _seed_case(501, 501)
        response = client.post("/api/cases/501/rca/suggest")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["draft"] is None


def test_rca_suggest_returns_draft_and_similar_case_ids_when_assistant_available(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Likely a bad deploy caused the CPU regression - verify recent releases.")
    assistant = _assistant_with(fake_client)
    similarity_service = _FakeSimilarityService(
        matches=[
            SimilarCaseMatch(
                case_id=999,
                similarity_score=0.9,
                title="Prior CPU regression",
                service="checkout-api",
                metric_name="cpu_usage",
                category="behavior_change",
                case_status="resolved",
                investigation_status="completed",
                rca_verified=True,
                root_cause_summary="Bad deploy introduced a busy loop.",
                corrective_action="Rolled back the deploy.",
                outcome_status="resolved",
                outcome_summary="Rolled back, CPU normalized.",
            )
        ]
    )
    app = client_factory(assistant=assistant, similarity_service=similarity_service)

    with TestClient(app) as client:
        _seed_case(502, 502)
        response = client.post("/api/cases/502/rca/suggest")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["draft"] == "Likely a bad deploy caused the CPU regression - verify recent releases."
    assert body["based_on_similar_cases"] == [999]


def test_rca_suggest_falls_back_cleanly_when_ai_call_fails(client_factory) -> None:
    fake_client = _ScriptedClient(raise_error=True)
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant, similarity_service=None)

    with TestClient(app) as client:
        _seed_case(503, 503)
        response = client.post("/api/cases/503/rca/suggest")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False


def test_rca_suggest_never_writes_to_the_case(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Draft hypothesis.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant, similarity_service=None)

    with TestClient(app) as client:
        _seed_case(504, 504)
        client.post("/api/cases/504/rca/suggest")
        case_after = client.get("/api/cases/504").json()

    assert case_after["root_cause_summary"] is None
    assert case_after["root_cause_status"] == "unknown"


# --- Resolution draft suggestion -----------------------------------------------------------


def test_resolution_suggest_unavailable_when_assistant_is_missing(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_case(505, 505, notes=[{"timestamp": "t", "note": "Rolled back the deploy."}])
        response = client.post("/api/cases/505/resolution/suggest")

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_resolution_suggest_unavailable_when_no_material_to_draft_from(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Should never be called.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_case(506, 506)
        response = client.post("/api/cases/506/resolution/suggest")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert fake_client.calls == []


def test_resolution_suggest_returns_draft_when_assistant_available(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Rolled back the offending deploy; CPU usage returned to baseline.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_case(
            507,
            507,
            notes=[{"timestamp": "t", "note": "Rolled back the deploy."}],
            root_cause_summary="Bad deploy introduced a busy loop.",
            corrective_action="Rolled back the deploy.",
        )
        response = client.post("/api/cases/507/resolution/suggest")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["draft"] == "Rolled back the offending deploy; CPU usage returned to baseline."


def test_resolution_suggest_never_writes_to_the_case(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Draft resolution.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_case(508, 508, root_cause_summary="Bad deploy.", corrective_action="Rolled back.")
        client.post("/api/cases/508/resolution/suggest")
        case_after = client.get("/api/cases/508").json()

    assert case_after["outcome_summary"] is None
    assert case_after["outcome_status"] == "pending"


# --- Existing PATCH endpoints stay fully functional and untouched -------------------------


def test_existing_rca_and_resolution_patch_endpoints_are_unaffected(client_factory) -> None:
    app = client_factory(assistant=None, similarity_service=None)

    with TestClient(app) as client:
        _seed_case(509, 509)

        rca_response = client.patch(
            "/api/cases/509/rca",
            json={"root_cause_status": "identified", "root_cause_summary": "Deploy caused CPU regression.", "root_cause_verified": True},
        )
        resolution_response = client.patch(
            "/api/cases/509/resolution",
            json={
                "outcome_status": "in_progress",
                "outcome_summary": "Rolled back the deploy.",
                "corrective_action": "Rolled back the deploy.",
            },
        )

    assert rca_response.status_code == 200
    assert rca_response.json()["root_cause_summary"] == "Deploy caused CPU regression."
    assert resolution_response.status_code == 200
    assert resolution_response.json()["outcome_summary"] == "Rolled back the deploy."


def test_suggest_rca_includes_external_ticket_comments(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Suggested root cause from ticket notes.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_case(510, 510)
        now = datetime.now(timezone.utc)
        session_local = get_session_local()
        with session_local() as db:
            from backend.app.models.entities import CaseTicketEventEntity
            db.add(
                CaseTicketEventEntity(
                    case_id=510,
                    provider="jira",
                    remote_event_id="comm-510",
                    event_type="comment_added",
                    occurred_at=now,
                    created_at=now,
                    author="Senior SRE",
                    summary="Connection pool leak verified in production auth service.",
                )
            )
            db.commit()

        response = client.post("/api/cases/510/rca/suggest")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert len(fake_client.calls) == 1
    evidence_sent = "\n".join(m.content for m in fake_client.calls[0].messages)
    assert "External team notes from Jira/ticketing:" in evidence_sent
    assert "[Senior SRE]: Connection pool leak verified" in evidence_sent


def test_suggest_resolution_includes_external_ticket_comments(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Suggested resolution from ticket notes.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_case(511, 511)
        now = datetime.now(timezone.utc)
        session_local = get_session_local()
        with session_local() as db:
            from backend.app.models.entities import CaseTicketEventEntity
            db.add(
                CaseTicketEventEntity(
                    case_id=511,
                    provider="jira",
                    remote_event_id="comm-511",
                    event_type="comment_added",
                    occurred_at=now,
                    created_at=now,
                    author="OnCall Engineer",
                    summary="Applied hotfix PR #123 and restarted connection poolers.",
                )
            )
            db.commit()

        response = client.post("/api/cases/511/resolution/suggest")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert len(fake_client.calls) == 1
    evidence_sent = "\n".join(m.content for m in fake_client.calls[0].messages)
    assert "External team notes from Jira/ticketing:" in evidence_sent
    assert "[OnCall Engineer]: Applied hotfix PR #123" in evidence_sent

