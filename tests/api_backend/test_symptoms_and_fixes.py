"""Near-copies folded, symptom and fix vectors, fix outcomes, same fix elsewhere and suggested
fixes - end to end with the real embedder and in-memory Qdrant (fixtures from test_memory_recall).
Skipped when the embedding model can't be loaded."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMResponse
from backend.app.memory.diversity import collapse_near_copies
from backend.app.memory.fix_outcomes import RECURRENCE_DAYS, find_same_fix, fix_outcomes
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.seen_before import find_seen_before
from backend.app.memory.suggested_fixes import draft_runbook, suggest_fixes
from backend.app.memory.vector_names import RESOLUTION_VECTOR, SYMPTOM_VECTOR
from backend.app.notifications.message_builder import _seen_before
from tests.api_backend.test_imported_case_recall import _import
from tests.api_backend.test_memory_recall import CATALOG, LATENCY, SERVICE, _add_case, _recall, embedder, memory  # noqa: F401
from tests.api_backend.test_novelty_and_recurring import MORE, _latency_finding

NOW = datetime.utcnow()
# Two checkout latency incidents fixed the same way, worded differently from the catalog's.
POOL_A = dict(
    service=SERVICE, metric=LATENCY, title="checkout-api latency up, connections exhausted",
    summary="checkout-api p95 latency rose from 200ms to 650ms.",
    root_cause="Database connection pool exhausted.", fix="Raised the database connection pool size.",
    outcome="Latency recovered.",
)
POOL_B = dict(POOL_A, title="checkout-api slow again, pool exhausted", summary="checkout-api p95 latency at 700ms during peak.")


def _case(db, memory, monkeypatch, key, *, spec=None, created_days=1, resolved_days=None, resolved=True):
    if spec is not None:
        monkeypatch.setitem(CATALOG, key, spec)
    elif key in MORE:
        monkeypatch.setitem(CATALOG, key, MORE[key])
    case = _add_case(db, key, resolved=resolved)
    case.created_at = NOW - timedelta(days=created_days)
    if resolved:
        case.resolved_at = case.updated_at = NOW - timedelta(days=resolved_days if resolved_days is not None else max(created_days - 1, 0))
    db.commit()
    memory.indexer.index_case(case, db)
    return case


def _point(case) -> str:
    return CaseMemoryIndexer._generate_point_id(case.id)


# --- near-copies (#7) --------------------------------------------------------------------------

def test_a_repeat_of_the_same_incident_folds_under_the_first(db_session, memory, monkeypatch):
    first = _case(db_session, memory, monkeypatch, "db_pool", created_days=40)
    repeat = _case(db_session, memory, monkeypatch, "db_pool_repeat", spec=CATALOG["db_pool"], created_days=10)
    other = _case(db_session, memory, monkeypatch, "db_pool_2", created_days=20)

    response = find_seen_before(db_session, _latency_finding(db_session), memory.similarity, memory.embedder)

    rows = {match.case_id: match for match in response.matches}
    folded = {copy.case_id for match in response.matches for copy in match.more_like_this}
    # The repeat sits under whichever of the two ranked higher; the differently fixed case is its own row.
    assert {first.id, repeat.id} & set(rows) and {first.id, repeat.id} & folded
    assert other.id in rows and other.id not in folded
    # The badge still counts the folded copy.
    assert response.novelty.matching_cases == 3


def test_similar_cases_and_alert_context_fold_repeats_too(db_session, memory, monkeypatch):
    source = _case(db_session, memory, monkeypatch, "db_pool_2", created_days=5)
    _case(db_session, memory, monkeypatch, "db_pool", created_days=40)
    _case(db_session, memory, monkeypatch, "db_pool_repeat", spec=CATALOG["db_pool"], created_days=30)

    similar = memory.similarity.find_similar_cases(source.id, db_session, minimum_score=0.4)
    assert sum(len(match.more_like_this) for match in similar.matches) == 1

    context = _recall(db_session, memory, "checkout latency is up, db connections maxed out")
    assert max(case.more_like_this for case in context.similar_cases) == 1


def test_slack_says_how_many_more_like_this():
    line = _seen_before({"similar_cases": [{"case_id": 4, "title": "pool", "similarity_score": 0.8, "more_like_this": 2}]}, "http://ui")

    assert "+2 more like this" in line


def test_near_copies_on_different_services_stay_apart():
    vector = [1.0, 0.0]
    results = [
        {"payload": {"case_id": 1, "service_key": "checkout-api"}, "vector": vector},
        {"payload": {"case_id": 2, "service_key": "payments-api"}, "vector": vector},
        {"payload": {"case_id": 3, "service_key": "checkout-api"}, "vector": vector},
        {"payload": {"case_id": 4, "service_key": "checkout-api"}},
    ]

    groups = collapse_near_copies(results)

    assert [(leader["payload"]["case_id"], [copy["payload"]["case_id"] for copy in copies]) for leader, copies in groups] == [
        (1, [3]), (2, []), (4, []),
    ]


# --- symptom and resolution vectors (8.1) ------------------------------------------------------

def test_an_imported_postmortem_is_now_a_strong_match_for_a_detected_finding(db_session, memory):
    ids = _import(db_session, memory)

    response = find_seen_before(db_session, _latency_finding(db_session), memory.similarity, memory.embedder)

    postmortem = next(match for match in response.matches if match.case_id == ids["PM-1"])
    assert postmortem.strength == "strong"


def test_the_fix_vector_appears_once_a_case_has_a_cause(db_session, memory, monkeypatch):
    open_case = _case(db_session, memory, monkeypatch, "db_pool", resolved=False)
    store = memory.similarity.vector_store
    assert store.get_vector(_point(open_case), SYMPTOM_VECTOR) is not None
    assert store.get_vector(_point(open_case), RESOLUTION_VECTOR) is None

    open_case.root_cause_summary, open_case.corrective_action = "Pool exhausted.", "Raised the pool size."
    db_session.commit()
    memory.indexer.index_case(open_case, db_session)

    assert store.get_vector(_point(open_case), RESOLUTION_VECTOR) is not None


# --- fix outcomes and same fix elsewhere (8.2) -------------------------------------------------

def test_fix_outcomes_are_inferred_from_what_happened_next(db_session, memory, monkeypatch):
    came_back = _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=90, resolved_days=80)
    # The same symptom on the same service 12 days after that fix.
    _case(db_session, memory, monkeypatch, "pool_b", spec=POOL_B, created_days=68, resolved=False)
    held = _case(db_session, memory, monkeypatch, "inventory_disk", created_days=120, resolved_days=100)
    too_early = _case(db_session, memory, monkeypatch, "auth_cert", created_days=6, resolved_days=5)
    open_case = _case(db_session, memory, monkeypatch, "payment_api", created_days=2, resolved=False)

    outcomes = fix_outcomes(db_session, memory.similarity.vector_store, [came_back, held, too_early, open_case])

    assert outcomes[came_back.id].status == "came_back"
    assert outcomes[came_back.id].came_back_after_days == 12 and outcomes[came_back.id].label == "Came back after 12 days"
    assert outcomes[held.id].status == "held" and outcomes[held.id].label == f"Held for {RECURRENCE_DAYS}+ days"
    assert outcomes[too_early.id].status == "too_early"
    assert outcomes[open_case.id].status == "not_fixed"


def test_same_fix_elsewhere_finds_the_same_cause_on_other_services(db_session, memory, monkeypatch):
    case = _case(db_session, memory, monkeypatch, "db_pool_errors", created_days=50)
    elsewhere = _case(db_session, memory, monkeypatch, "db_pool_payments", created_days=40)
    same_words = _case(db_session, memory, monkeypatch, "db_pool_errors_again", spec=CATALOG["db_pool_errors"], created_days=20)
    # An open case has no fix vector; fix search must still run on fix vectors, not fall back.
    _case(db_session, memory, monkeypatch, "db_pool_3", created_days=3, resolved=False)
    unrelated = [
        _case(db_session, memory, monkeypatch, key, created_days=30).id for key in ("payment_api", "auth_cert", "inventory_disk")
    ]

    response = find_same_fix(db_session, memory.similarity.vector_store, memory.embedder, case)

    assert response.available and response.outcome is not None
    found = {match.case_id: match for match in response.matches}
    assert elsewhere.id in found and found[elsewhere.id].service == "payments-api"
    assert found[same_words.id].similarity_score > 0.99
    # The open case shares the cause but has no fix yet, so it is not "the same fix".
    assert all(match.corrective_action for match in response.matches)
    assert not set(unrelated) & set(found)
    assert all(match.outcome.status in {"held", "came_back", "too_early", "unknown"} for match in response.matches)


def test_same_fix_needs_a_recorded_cause_or_fix(db_session, memory, monkeypatch):
    open_case = _case(db_session, memory, monkeypatch, "db_pool", resolved=False)

    response = find_same_fix(db_session, memory.similarity.vector_store, memory.embedder, open_case)

    assert not response.available and "No cause or fix" in response.reason


# --- suggested fixes and runbook draft (8.3) ---------------------------------------------------

def _history(db, memory, monkeypatch):
    held = _case(db, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=200, resolved_days=190)
    came_back = _case(db, memory, monkeypatch, "pool_b", spec=POOL_B, created_days=70, resolved_days=60)
    _case(db, memory, monkeypatch, "db_pool_3", created_days=48, resolved=False)
    too_early = _case(db, memory, monkeypatch, "payment_api", created_days=8, resolved_days=6)
    return held, came_back, too_early


def test_suggested_fixes_merge_the_same_fix_and_rank_by_how_often_it_held(db_session, memory, monkeypatch):
    held, came_back, too_early = _history(db_session, memory, monkeypatch)
    finding = _latency_finding(db_session)
    seen = find_seen_before(db_session, finding, memory.similarity, memory.embedder)

    response = suggest_fixes(db_session, memory.similarity.vector_store, seen)

    assert response.available
    pool, *rest = response.fixes
    assert {source.case_id for source in pool.sources} == {held.id, came_back.id}
    assert (pool.held, pool.came_back, pool.label) == (1, 1, "Held 1 of 2 times")
    assert pool.fix == POOL_A["fix"]
    payment = next(fix for fix in rest if too_early.id in {source.case_id for source in fix.sources})
    assert payment.label == "Too early to tell"


def test_a_fix_that_never_held_says_it_came_back(db_session, memory, monkeypatch):
    _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=90, resolved_days=80)
    _case(db_session, memory, monkeypatch, "pool_b", spec=POOL_B, created_days=68, resolved=False)
    seen = find_seen_before(db_session, _latency_finding(db_session), memory.similarity, memory.embedder)

    fix = suggest_fixes(db_session, memory.similarity.vector_store, seen).fixes[0]

    assert (fix.held, fix.came_back, fix.label) == (0, 1, "Came back 1 of 1 time")


class _Writer:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return LLMResponse(content="1. Check pool usage (case #1).\n2. Raise the pool size (case #1).")


def test_a_runbook_draft_cites_the_past_fixes_and_needs_ai(db_session, memory, monkeypatch):
    _history(db_session, memory, monkeypatch)
    finding = _latency_finding(db_session)
    suggestions = suggest_fixes(db_session, memory.similarity.vector_store, find_seen_before(db_session, finding, memory.similarity, memory.embedder))
    writer = _Writer()

    draft = draft_runbook(finding.title, suggestions, OptionalAIServices(client=writer, structured=None))

    assert draft.available and draft.draft.startswith("1. Check pool usage")
    evidence = writer.requests[0].messages[1].content
    assert POOL_A["fix"] in evidence and "Held 1 of 2 times" in evidence
    assert set(draft.based_on_cases) == {source.case_id for fix in suggestions.fixes for source in fix.sources}
    assert not draft_runbook(finding.title, suggestions, None).available


def test_the_new_endpoints_say_when_memory_is_off(client, db_session):
    assert client.get("/api/findings/999/suggested-fixes").status_code == 404
    assert client.get("/api/cases/999/same-fix").status_code == 404
