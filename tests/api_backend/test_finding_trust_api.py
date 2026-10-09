from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import MemoryConfig
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, FindingFeedbackEntity, SignalEntity
from backend.app.services import finding_trust as ft
from backend.app.services.finding_trust import SignalFacts, trust_group


def _facts(*pairs: tuple[str | None, str]) -> list[SignalFacts]:
    return [SignalFacts(analyzer, signal_type) for analyzer, signal_type in pairs]


@pytest.mark.parametrize(
    ("category", "signals", "group"),
    [
        ("behavior_change", _facts(("pyod_outlier", "anomaly"), ("ruptures", "ruptures")), "level_change_agree"),
        # ruptures and baseline_shift run the same change detector: one check, not two.
        ("behavior_change", _facts(("ruptures", "ruptures"), ("baseline_shift", "baseline_shift")), "level_change_single"),
        ("behavior_change", _facts(("ruptures", "ruptures")), "level_change_single"),
        ("unusual_activity", _facts(("pyod_outlier", "anomaly")), "spike"),
        ("behavior_change", _facts(("trend", "trend")), "pattern"),
        ("operational_insight", _facts(("prophet", "forecast")), "pattern"),
        ("data_quality", _facts(("data_health", "data_gap")), "data_problem"),
        # No stored signals: the category decides.
        ("behavior_change", [], "level_change_single"),
        ("unusual_activity", [], "spike"),
        ("data_quality", [], "data_problem"),
    ],
)
def test_trust_group_follows_the_kinds_of_checks_behind_a_finding(category, signals, group) -> None:
    assert trust_group(category, signals)[0] == group


def test_tested_evidence_needs_enough_checked_and_says_whether_the_metric_fits() -> None:
    config = {"min_checked": 30, "source": {"measured_at": "2026-10-08"}, "groups": {
        "level_change_agree": {"tested": {"real": 0.91, "checked": 266, "random": 0.6}},
        "spike": {"tested": {"real": 0.6, "checked": 12, "random": 0.6}},
    }}
    latency = ft.tested_evidence("level_change_agree", "http_request_duration_seconds", config)
    assert latency["real"] == 0.91 and latency["fits_metric"] is True and latency["measured_at"] == "2026-10-08"
    assert ft.tested_evidence("level_change_agree", "orders_placed_total", config)["fits_metric"] is False
    assert ft.tested_evidence("spike", "cpu", config) is None
    assert ft.tested_evidence("pattern", "cpu", config) is None


def test_shipped_trust_config_has_tested_numbers_for_the_needs_attention_groups() -> None:
    config = ft.load_trust_config()
    for group in ("level_change_agree", "level_change_single"):
        tested = config["groups"][group]["tested"]
        assert tested["checked"] >= config["min_checked"]
        assert tested["real"] > tested["random"]


def _seed_finding(db, finding_id: int, service: str, signals: list[tuple[str, str]], category: str = "behavior_change") -> None:
    now = datetime.now(timezone.utc)
    signal_ids = []
    for index, (analyzer, signal_type) in enumerate(signals):
        signal_id = f"sig-{finding_id}-{index}"
        signal_ids.append(signal_id)
        db.add(SignalEntity(signal_id=signal_id, signal_type=signal_type, analyzer_id=analyzer, metric_name="cpu_usage", service=service,
                            severity="high", start_time=now, end_time=now, evidence_json={}, importance_score=0.7, analysis_run_id="run-1"))
    db.add(FindingEntity(id=finding_id, analysis_run_id="run-1", service=service, metric_name="cpu_usage", title=f"finding {finding_id}",
                         summary="s", category=category, health_status="significant", importance_score=0.7, investigation_priority=2,
                         signal_ids=signal_ids, comparison_json={}, created_at=now))


@pytest.fixture()
def seeded(client: TestClient):
    with get_session_local()() as db:
        for finding_id in range(1, 8):
            _seed_finding(db, finding_id, "cart", [("pyod_outlier", "anomaly"), ("ruptures", "ruptures")])
        _seed_finding(db, 20, "cart", [("pyod_outlier", "anomaly")], category="unusual_activity")
        _seed_finding(db, 30, "payments", [("pyod_outlier", "anomaly"), ("ruptures", "ruptures")])
        db.commit()
    return client


def test_findings_carry_trust_with_tested_numbers(seeded: TestClient) -> None:
    by_id = {item["id"]: item["trust"] for item in seeded.get("/api/findings").json()}

    strong = by_id[1]
    assert (strong["group"], strong["tier"], strong["badge"], strong["moved"]) == ("level_change_agree", "needs_attention", "strong", None)
    assert strong["tested"]["checked"] >= 30 and strong["tested"]["fits_metric"] is True
    assert strong["service"] == {"real": 0, "answered": 0, "min_answers": 5}
    assert strong["your_answer"] is None

    spike = by_id[20]
    assert (spike["group"], spike["tier"], spike["badge"]) == ("spike", "context", None)


def test_feedback_builds_the_services_own_rate_per_group(seeded: TestClient) -> None:
    for finding_id in (1, 2, 3, 4):
        assert seeded.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}).status_code == 200
    seeded.post("/api/findings/5/feedback", json={"verdict": "not_a_problem"})
    # An expected change is neither real nor a false alarm: it doesn't count.
    seeded.post("/api/findings/6/feedback", json={"verdict": "expected_change"})
    # Answering again changes the answer instead of adding one.
    seeded.post("/api/findings/5/feedback", json={"verdict": "real_problem"})
    response = seeded.post("/api/findings/7/feedback", json={"verdict": "not_a_problem"})

    trust = response.json()["trust"]
    assert trust["your_answer"] == "not_a_problem"
    assert trust["service"] == {"real": 5, "answered": 6, "min_answers": 5}

    by_id = {item["id"]: item["trust"] for item in seeded.get("/api/findings").json()}
    assert by_id[6]["your_answer"] == "expected_change"
    # Other services and other groups keep their own counts.
    assert by_id[30]["service"]["answered"] == 0
    assert by_id[20]["service"]["answered"] == 0


def test_feedback_rejects_unknown_verdicts_and_findings(seeded: TestClient) -> None:
    assert seeded.post("/api/findings/1/feedback", json={"verdict": "maybe"}).status_code == 422
    assert seeded.post("/api/findings/999/feedback", json={"verdict": "real_problem"}).status_code == 404


@pytest.mark.parametrize(
    ("group", "real", "answered", "expected"),
    [
        # Fewer than 5 answers never move anything, however one-sided.
        ("spike", 4, 4, ("context", None, None)),
        ("level_change_agree", 0, 4, ("needs_attention", "strong", None)),
        # A context group the team mostly confirms moves up, for that service.
        ("spike", 3, 6, ("needs_attention", "team_confirmed", "up")),
        ("pattern", 5, 5, ("needs_attention", "team_confirmed", "up")),
        ("spike", 2, 5, ("context", None, None)),
        # A needs-attention group the team mostly rejects moves down.
        ("level_change_agree", 0, 5, ("context", None, "down")),
        ("level_change_single", 1, 6, ("context", None, "down")),
        ("level_change_single", 1, 5, ("needs_attention", "moderate", None)),
        # A metric that stopped reporting is a fact: it stays, whatever the answers.
        ("data_problem", 0, 9, ("needs_attention", "data_problem", None)),
    ],
)
def test_placement_moves_a_group_only_on_enough_one_sided_answers(group, real, answered, expected) -> None:
    assert ft.placement(group, real, answered) == expected


def test_answers_move_a_kind_of_finding_between_lists_for_that_service_only(client: TestClient) -> None:
    with get_session_local()() as db:
        for finding_id in range(1, 7):
            _seed_finding(db, finding_id, "cart", [("pyod_outlier", "anomaly")], category="unusual_activity")
        _seed_finding(db, 7, "payments", [("pyod_outlier", "anomaly")], category="unusual_activity")
        for finding_id in range(10, 16):
            _seed_finding(db, finding_id, "cart", [("pyod_outlier", "anomaly"), ("ruptures", "ruptures")])
        db.commit()

    for finding_id in range(1, 6):
        client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"})
    for finding_id in range(10, 15):
        client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "not_a_problem"})

    by_id = {item["id"]: item["trust"] for item in client.get("/api/findings").json()}
    # Spikes on cart moved up, including one nobody answered; payments' spike didn't.
    assert (by_id[6]["tier"], by_id[6]["badge"], by_id[6]["moved"]) == ("needs_attention", "team_confirmed", "up")
    assert (by_id[7]["tier"], by_id[7]["moved"]) == ("context", None)
    # Strong level changes on cart moved down after five "not a problem" answers.
    assert (by_id[15]["tier"], by_id[15]["badge"], by_id[15]["moved"]) == ("context", None, "down")

    # Changing answers moves it back.
    for finding_id in range(10, 13):
        client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"})
    trust = {item["id"]: item["trust"] for item in client.get("/api/findings").json()}[15]
    assert (trust["tier"], trust["badge"], trust["moved"]) == ("needs_attention", "strong", None)


def test_resetting_operational_data_also_clears_the_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_ENABLE_TESTING_API", "true")
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            with get_session_local()() as db:
                _seed_finding(db, 1, "cart", [("pyod_outlier", "anomaly"), ("ruptures", "ruptures")])
                db.commit()
            client.post("/api/findings/1/feedback", json={"verdict": "not_a_problem"})

            response = client.post("/api/testing/reset-operational-data", json={"confirm": "RESET_OPS_SIGNALS_TEST_DATA", "clear_vector_memory": False})

            assert response.json()["deleted_rows"]["ops_finding_feedback"] == 1
            with get_session_local()() as db:
                assert db.query(FindingFeedbackEntity).count() == 0
