"""One case per problem. Each run that sees a problem again stores a new finding linked to the first
by problem_id; Create Case on any of them opens the problem's case instead of a second one, and the
places that show a finding's case find it through the problem."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.main import create_app
from backend.app.memory.seen_before import find_seen_before
from backend.app.models.db import get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.problem_cases import case_for_finding_problem, cases_of_problems, problems_of
from tests.api_backend.test_cases import _create_finding


def _problem(runs: int = 2) -> list[int]:
    """A problem seen by `runs` analysis runs: the first finding and its later runs' findings."""
    first = _create_finding(analysis_run_id="run-problem-0")
    return [first, *(_create_finding(analysis_run_id=f"run-problem-{run}", problem_id=first) for run in range(1, runs))]


def _case_count(db) -> int:
    return db.scalar(select(func.count()).select_from(OperationalCaseEntity))


def test_create_case_on_a_later_run_opens_the_problems_case(client, db_session) -> None:
    first, later = _problem()
    opened = client.post(f"/api/cases/findings/{first}/create").json()

    again = client.post(f"/api/cases/findings/{later}/create")

    assert again.status_code == 200
    assert again.json()["case_id"] == opened["case_id"]
    # The finding asked about: callers such as New Analysis key the case by it.
    assert again.json()["finding_id"] == later
    assert again.json()["existing"] is True
    assert opened["existing"] is False
    assert _case_count(db_session) == 1


def test_a_case_opened_on_a_later_run_is_found_from_the_first_finding(client, db_session) -> None:
    first, second, third = _problem(runs=3)
    opened = client.post(f"/api/cases/findings/{second}/create").json()

    assert client.post(f"/api/cases/findings/{first}/create").json()["case_id"] == opened["case_id"]
    assert client.post(f"/api/cases/findings/{third}/create").json()["case_id"] == opened["case_id"]
    assert _case_count(db_session) == 1


def test_a_closed_case_is_opened_not_replaced(client, db_session) -> None:
    first, later = _problem()
    opened = client.post(f"/api/cases/findings/{first}/create").json()
    case = db_session.get(OperationalCaseEntity, opened["case_id"])
    case.case_status = "resolved"
    case.outcome_status = "resolved"
    db_session.commit()

    again = client.post(f"/api/cases/findings/{later}/create").json()

    assert again["case_id"] == opened["case_id"]
    assert again["case_status"] == "resolved"
    assert _case_count(db_session) == 1


def test_a_different_problem_gets_its_own_case(client, db_session) -> None:
    first, _later = _problem()
    came_back = _create_finding(analysis_run_id="run-came-back")

    one = client.post(f"/api/cases/findings/{first}/create").json()
    other = client.post(f"/api/cases/findings/{came_back}/create").json()

    assert other["case_id"] != one["case_id"]
    assert other["existing"] is False
    assert _case_count(db_session) == 2


def test_problem_helpers_map_findings_and_pick_the_first_case(db_session) -> None:
    first, later = _problem()
    lone = _create_finding(analysis_run_id="run-lone")
    # Two cases on one problem, as before this rule: the first one opened is the problem's case.
    for finding_id in (later, first):
        db_session.add(OperationalCaseEntity(finding_id=finding_id, analysis_run_id="run", case_title="t", finding_snapshot={}))
    db_session.commit()
    older = db_session.scalars(select(OperationalCaseEntity).order_by(OperationalCaseEntity.id)).first()

    assert problems_of(db_session, [first, later, lone, 999_999]) == {first: first, later: first, lone: lone}
    assert cases_of_problems(db_session, [first, lone]) == {first: older}
    assert case_for_finding_problem(db_session, db_session.get(FindingEntity, lone)) is None
    assert case_for_finding_problem(db_session, db_session.get(FindingEntity, later), lock=True) is older
    assert problems_of(db_session, []) == {}
    assert cases_of_problems(db_session, []) == {}


class _OneResultStore:
    def __init__(self, case_ids: list[int]) -> None:
        self.case_ids = case_ids

    def search(self, **_kwargs):
        return [{"score": 0.95, "payload": {"case_id": case_id}} for case_id in self.case_ids]


def test_seen_before_leaves_out_the_problems_own_case(db_session) -> None:
    first, later = _problem()
    other_problem = _create_finding(analysis_run_id="run-past")
    own = OperationalCaseEntity(finding_id=first, analysis_run_id="run", case_title="this problem", finding_snapshot={"service": "checkout-service"})
    past = OperationalCaseEntity(finding_id=other_problem, analysis_run_id="run", case_title="past problem", finding_snapshot={"service": "checkout-service"})
    db_session.add_all([own, past])
    db_session.commit()
    similarity = SimpleNamespace(vector_store=_OneResultStore([own.id, past.id]))
    embedder = SimpleNamespace(encode=lambda _text: [0.0])

    response = find_seen_before(db_session, db_session.get(FindingEntity, later), similarity, embedder)

    assert [match.case_id for match in response.matches] == [past.id]


def test_alerts_show_the_problems_case_on_a_later_runs_finding() -> None:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client, get_session_local()() as db:
        first = FindingEntity(metric_name="latency", service="checkout-api", title="Latency shift", summary="p95 up", category="behavior_change", health_status="critical")
        db.add(first)
        db.flush()
        later = FindingEntity(metric_name="latency", service="checkout-api", title="Latency shift", summary="p95 up", category="behavior_change", health_status="critical", problem_id=first.id)
        db.add(later)
        db.flush()
        case = OperationalCaseEntity(finding_id=first.id, analysis_run_id="run-1", case_title="Latency shift", finding_snapshot={})
        db.add(case)
        now = datetime.utcnow()
        db.add(
            AlertEnrichmentEntity(
                fingerprint="fp-latency", source="alertmanager", alert_name="HighLatency", status="firing", service="checkout-api",
                severity="critical", starts_at=now - timedelta(minutes=3), created_at=now - timedelta(minutes=3),
                labels_json={}, annotations_json={}, finding_id=later.id, message_json={},
            )
        )
        db.commit()
        case_id = case.id

        body = client.get("/api/alerts").json()

    assert body[0]["case_id"] == case_id


def _listed(client) -> dict[int, dict]:
    return {finding["id"]: finding for finding in client.get("/api/findings").json()}


def test_findings_say_which_case_their_problem_has(client) -> None:
    first, later = _problem()
    other = _create_finding(analysis_run_id="run-other", title="Memory went up")
    assert _listed(client)[later]["case_id"] is None

    opened = client.post(f"/api/cases/findings/{first}/create").json()

    listed = _listed(client)
    # Every run's finding of the problem carries its case, so each card says Open Case.
    assert listed[first]["case_id"] == opened["case_id"]
    assert listed[later]["case_id"] == opened["case_id"]
    assert listed[later]["case_status"] == "open"
    assert listed[other]["case_id"] is None


def test_a_finding_of_a_resolved_problem_still_points_at_its_case(client, db_session) -> None:
    first, later = _problem()
    opened = client.post(f"/api/cases/findings/{first}/create").json()
    case = db_session.get(OperationalCaseEntity, opened["case_id"])
    case.case_status = "resolved"
    db_session.commit()

    listed = _listed(client)[later]

    assert listed["case_id"] == opened["case_id"]
    assert listed["case_status"] == "resolved"
