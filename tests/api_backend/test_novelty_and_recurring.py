""""First time seen?" badges and recurring-problem groups.

Novelty is a rule over matches, tested directly. Recurring problems run end to end with the real
embedder and in-memory Qdrant (fixtures from test_memory_recall.py), plus a fake store for the
grouping shape itself. Skipped when the embedding model can't be loaded."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMResponse
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.novelty import RECURRING_MIN_MATCHES, assess_novelty
from backend.app.memory.recurring import GROUP_SIMILARITY, find_recurring_problems
from backend.app.memory.seen_before import find_seen_before
from backend.app.models.entities import FindingEntity
from tests.api_backend.test_memory_recall import CATALOG, LATENCY, SERVICE, _add_case, embedder, memory  # noqa: F401

# More checkout latency incidents, worded differently, and a second disk incident: with the
# catalog's own cases these give one big recurring symptom, one pair, and some one-offs.
MORE = {
    "db_pool_2": dict(
        service=SERVICE, metric=LATENCY, title="checkout-api slow: connection pool saturated",
        summary="checkout-api p95 latency rose to 600ms during the evening peak.",
        root_cause="Connection pool to Postgres saturated; requests queued for a connection.",
        fix="Raised max pool size to 60.", outcome="Latency normal.",
    ),
    "db_pool_3": dict(
        service=SERVICE, metric=LATENCY, title="checkout-api latency regression, pool exhausted again",
        summary="Sustained latency baseline shift on checkout-api: p95 at 500ms.",
        root_cause="Database connection pool exhausted after traffic growth.",
        fix="Added pgbouncer.", outcome="Recovered.",
    ),
    "disk_2": dict(
        service="inventory-svc", metric="node_filesystem_avail_bytes", title="inventory-svc disk almost full",
        summary="Free disk on inventory-svc dropped below 5%.",
        root_cause="Old logs not rotated.", fix="Rotated logs, enabled logrotate.", outcome="Disk freed.",
    ),
}


def _match(score: float, same_service: bool = True) -> SimpleNamespace:
    return SimpleNamespace(similarity_score=score, same_service=same_service)


# --- novelty -----------------------------------------------------------------------------------

def test_nothing_in_memory_is_a_new_pattern():
    novelty = assess_novelty([], "checkout-api")

    assert novelty.level == "new" and novelty.label == "New pattern"
    assert novelty.matching_cases == 0 and novelty.best_score is None


def test_matches_only_elsewhere_are_new_on_this_service():
    novelty = assess_novelty([_match(0.8, same_service=False), _match(0.5, same_service=False)], "checkout-api")

    assert novelty.level == "new_on_service"
    assert novelty.label == "First time on checkout-api"
    assert (novelty.matching_cases, novelty.all_matching_cases) == (0, 2)


def test_a_few_same_service_matches_are_seen_before():
    novelty = assess_novelty([_match(0.55), _match(0.9, same_service=False)], "checkout-api")

    assert novelty.level == "seen_before"
    assert novelty.matching_cases == 1 and novelty.best_score == 0.55


def test_enough_same_service_matches_are_recurring():
    novelty = assess_novelty([_match(0.7)] * RECURRING_MIN_MATCHES, "checkout-api")

    assert novelty.level == "recurring"
    assert novelty.label == f"Recurring · {RECURRING_MIN_MATCHES} past cases"


def test_without_a_service_every_match_counts():
    novelty = assess_novelty([_match(0.6, same_service=False)] * RECURRING_MIN_MATCHES, None)

    assert novelty.level == "recurring" and "in memory" in novelty.explanation


def _latency_finding(db) -> FindingEntity:
    finding = FindingEntity(
        analysis_run_id="run-new", service=SERVICE, metric_name=LATENCY,
        title="checkout-api p95 latency baseline shift", summary="p95 latency on checkout-api moved from 180ms to 470ms.",
        category="baseline_shift", health_status="significant", importance_score=0.8, investigation_priority=2,
        signal_ids=["sig-1"], comparison_json={}, created_at=datetime.utcnow(),
    )
    db.add(finding)
    db.commit()
    return finding


def _remember(db, memory, keys, monkeypatch, *, age_days: dict[str, int] | None = None) -> dict[str, int]:
    ids = {}
    for key in keys:
        if key in MORE:
            monkeypatch.setitem(CATALOG, key, MORE[key])
        case = _add_case(db, key)
        if age_days and key in age_days:
            case.created_at = datetime.utcnow() - timedelta(days=age_days[key])
            db.commit()
        memory.indexer.index_case(case, db)
        ids[key] = case.id
    return ids


def test_seen_before_reports_how_familiar_the_finding_is(db_session, memory, monkeypatch):
    _remember(db_session, memory, ["db_pool", "inventory_disk"], monkeypatch)
    response = find_seen_before(db_session, _latency_finding(db_session), memory.similarity, memory.embedder)
    assert response.novelty.level == "seen_before"

    _remember(db_session, memory, ["db_pool_2", "db_pool_3"], monkeypatch)
    response = find_seen_before(db_session, _latency_finding(db_session), memory.similarity, memory.embedder)
    assert response.novelty.level == "recurring"
    assert response.novelty.matching_cases >= RECURRING_MIN_MATCHES


def test_similar_cases_report_novelty_too(db_session, memory, monkeypatch):
    ids = _remember(db_session, memory, ["db_pool", "auth_cert"], monkeypatch)

    response = memory.similarity.find_similar_cases(ids["auth_cert"], db_session, minimum_score=0.4)

    assert response.novelty.level in {"new", "new_on_service"}


# --- recurring problems ------------------------------------------------------------------------

ALL = ["db_pool", "payment_api", "db_pool_errors", "db_pool_payments", "inventory_disk", "auth_cert", "db_pool_2", "db_pool_3", "disk_2"]


def test_cases_that_keep_coming_back_are_grouped(db_session, memory, monkeypatch):
    ids = _remember(db_session, memory, ALL, monkeypatch)
    store = memory.similarity.vector_store

    response = find_recurring_problems(db_session, store, days=90, min_occurrences=3)

    assert response.available and response.cases_considered == len(ALL)
    assert len(response.problems) == 1
    problem = response.problems[0]
    members = {case.case_id for case in problem.cases}
    assert {ids["db_pool"], ids["db_pool_2"], ids["db_pool_3"]} <= members
    assert ids["auth_cert"] not in members and ids["inventory_disk"] not in members
    assert problem.occurrences == len(members) and SERVICE in problem.services
    assert all(case.similarity_to_central >= GROUP_SIMILARITY["symptom"] for case in problem.cases)
    assert problem.named_by == "central_case" and problem.name
    # Every catalog case is resolved with a verified cause, so each one's cause is listed.
    assert problem.verified_root_causes == problem.occurrences
    assert problem.causes and all(cause.verified for cause in problem.causes)

    pairs = find_recurring_problems(db_session, store, days=90, min_occurrences=2)
    disk = [problem for problem in pairs.problems if ids["inventory_disk"] in {case.case_id for case in problem.cases}]
    assert len(disk) == 1 and {case.case_id for case in disk[0].cases} == {ids["inventory_disk"], ids["disk_2"]}


def test_only_cases_inside_the_window_count(db_session, memory, monkeypatch):
    _remember(db_session, memory, ["db_pool", "db_pool_2", "db_pool_3"], monkeypatch, age_days={"db_pool_3": 200})

    response = find_recurring_problems(db_session, memory.similarity.vector_store, days=90, min_occurrences=3)

    assert response.cases_considered == 2 and response.problems == []
    assert len(find_recurring_problems(db_session, memory.similarity.vector_store, days=365, min_occurrences=3).problems) == 1


class _Naming:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def generate(self, request):
        return LLMResponse(content=self.reply)


def test_an_llm_names_the_groups_and_a_bad_reply_falls_back(db_session, memory, monkeypatch):
    _remember(db_session, memory, ["db_pool", "db_pool_2", "db_pool_3"], monkeypatch)
    store = memory.similarity.vector_store

    named = find_recurring_problems(db_session, store, ai_services=OptionalAIServices(client=_Naming("1. Checkout latency from DB pool exhaustion"), structured=None))
    assert named.problems[0].name == "Checkout latency from DB pool exhaustion"
    assert named.problems[0].named_by == "ai"

    unnamed = find_recurring_problems(db_session, store, ai_services=OptionalAIServices(client=_Naming("Sure! Here are some names."), structured=None))
    assert unnamed.problems[0].named_by == "central_case"


def test_without_memory_there_is_nothing_to_compare(db_session):
    response = find_recurring_problems(db_session, None)

    assert not response.available and "not enabled" in response.reason


class _PairsStore:
    """Distance-matrix answers for a chain: A~B, B~C, C~D, but A, C and D are not alike."""

    def __init__(self, point_ids: list[str]) -> None:
        a, b, c, d = point_ids
        self.pairs = [(a, b, 0.9), (b, c, 0.85), (c, d, 0.9), (a, c, 0.5), (a, d, 0.3), (b, d, 0.6)]

    def similarity_pairs(self, filters=None, sample=500, neighbours=20, using=None):
        return self.pairs


def test_a_chain_of_loose_look_alikes_is_not_one_group(db_session, monkeypatch):
    keys = ["db_pool", "payment_api", "db_pool_errors", "db_pool_payments"]
    cases = [_add_case(db_session, key) for key in keys]
    for case in cases:
        case.memory_status = "indexed"
    db_session.commit()
    store = _PairsStore([CaseMemoryIndexer._generate_point_id(case.id) for case in cases])

    response = find_recurring_problems(db_session, store, min_occurrences=3)

    # B (or C) centres a group with its two direct neighbours; the fourth case is left out rather
    # than chained in through a neighbour's neighbour.
    assert len(response.problems) == 1
    assert response.problems[0].occurrences == 3


def test_the_endpoint_says_when_memory_is_off(client):
    body = client.get("/api/memory/recurring-problems?days=30&min_occurrences=2").json()

    assert body["available"] is False and body["window_days"] == 30 and body["min_occurrences"] == 2


def test_comparison_failures_are_reported_not_raised(db_session, monkeypatch):
    class _Broken:
        def similarity_pairs(self, **_kwargs):
            raise RuntimeError("qdrant down")

    for key in ["db_pool", "db_pool_errors", "auth_cert"]:
        _add_case(db_session, key).memory_status = "indexed"
    db_session.commit()

    response = find_recurring_problems(db_session, _Broken())

    assert not response.available and response.reason == "Past cases could not be compared."
