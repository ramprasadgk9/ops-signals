"""The fix that didn't stick: a finding or case back soon after a case on its service was fixed -
end to end with the real embedder and in-memory Qdrant (fixtures from test_memory_recall).
Skipped when the embedding model can't be loaded."""

from __future__ import annotations

import json
from datetime import datetime

from backend.app.ai.factory import OptionalAIServices
from backend.app.api import assistant as assistant_module
from backend.app.api import memory as memory_module
from backend.app.memory.fix_came_back import CaseFixCameBackResponse, find_case_fix_came_back, split_still_open
from backend.app.memory.schemas import CameBackAfterFix
from backend.app.services.fix_came_back_why import why_facts, write_why
from tests.api_backend.test_cases_ai_drafts import _assistant_with, _ScriptedClient
from backend.app.memory.seen_before import find_seen_before
from tests.api_backend.test_memory_recall import _add_case, embedder, memory  # noqa: F401
from tests.api_backend.test_novelty_and_recurring import _latency_finding
from tests.api_backend.test_symptoms_and_fixes import POOL_A, POOL_B, _case


def _seen(db, memory):
    return find_seen_before(db, _latency_finding(db), memory.similarity, memory.embedder)


def test_a_finding_soon_after_a_fix_says_the_fix_did_not_stick(db_session, memory, monkeypatch):
    fixed = _case(db_session, memory, monkeypatch, "pool_a", spec=dict(POOL_A, fix="Rolled back to v2.2. Still open: fix the retry loop."), created_days=5, resolved_days=3)

    came_back = _seen(db_session, memory).came_back

    assert came_back is not None and came_back.case_id == fixed.id
    assert came_back.days == 3
    assert (came_back.fix, came_back.still_open) == ("Rolled back to v2.2.", "fix the retry loop.")


def test_the_latest_matching_fix_is_named(db_session, memory, monkeypatch):
    _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=25, resolved_days=20)
    # Close enough to the finding to count (POOL_B's wording scores just under the bar).
    latest = _case(db_session, memory, monkeypatch, "pool_a2", spec=dict(POOL_A, fix="Rolled back the pool change."), created_days=9, resolved_days=7)

    assert _seen(db_session, memory).came_back.case_id == latest.id


def test_no_warning_after_the_window_without_a_fix_or_on_another_service(db_session, memory, monkeypatch):
    _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=50, resolved_days=40)
    _case(db_session, memory, monkeypatch, "pool_open", spec=POOL_A, created_days=3, resolved=False)
    _case(db_session, memory, monkeypatch, "pool_other", spec=dict(POOL_A, service="payments-api"), created_days=4, resolved_days=2)

    assert _seen(db_session, memory).came_back is None


def test_a_new_case_names_the_earlier_fix_and_the_old_case_says_it_did_not_hold(db_session, memory, monkeypatch):
    old = _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=10, resolved_days=6)
    new = _case(db_session, memory, monkeypatch, "pool_b", spec=POOL_B, created_days=2, resolved=False)
    store = memory.similarity.vector_store

    on_new = find_case_fix_came_back(db_session, store, memory.embedder, new)
    on_old = find_case_fix_came_back(db_session, store, memory.embedder, old)

    assert on_new.came_back.case_id == old.id and on_new.came_back.days == 4
    assert on_new.fix_outcome is None
    assert on_old.came_back is None
    assert on_old.fix_outcome.status == "came_back" and on_old.fix_outcome.came_back_case_id == new.id


def test_a_fix_that_held_or_is_too_new_to_judge_is_not_flagged(db_session, memory, monkeypatch):
    fixed = _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=4, resolved_days=3)

    response = find_case_fix_came_back(db_session, memory.similarity.vector_store, memory.embedder, fixed)

    assert response.available and response.came_back is None and response.fix_outcome is None


def test_still_open_is_split_off_the_fix():
    assert split_still_open("Rolled back. Still open: fix the loop") == ("Rolled back.", "fix the loop")
    assert split_still_open("Raised the pool size.") == ("Raised the pool size.", None)
    assert split_still_open("Still open: everything") == ("Still open: everything", "everything")


def test_the_case_endpoint_says_when_memory_is_off(client, db_session, monkeypatch):
    assert client.get("/api/cases/999/fix-came-back").status_code == 404
    case = _add_case(db_session, "db_pool")

    body = client.get(f"/api/cases/{case.id}/fix-came-back").json()

    assert body["available"] is False and body["came_back"] is None


# --- "Why might it not have held?" (AI, optional) ----------------------------------------------

ROLLBACK = dict(POOL_A, root_cause="A retry loop in v2.3 doesn't release connections.", fix="Rolled back to v2.2. Still open: fix the retry loop.")


def _came_back(case) -> CameBackAfterFix:
    return CameBackAfterFix(case_id=case.id, title=case.case_title, fixed_at=datetime.utcnow(), days=3, fix="Rolled back to v2.2.", still_open="fix the retry loop.")


def _ai(reasons) -> OptionalAIServices:
    return OptionalAIServices(client=_ScriptedClient(response_text=json.dumps({"reasons": reasons})), structured=None)


def test_reasons_come_from_the_past_case_and_drop_made_up_details(db_session, memory, monkeypatch):
    past = _case(db_session, memory, monkeypatch, "rollback", spec=ROLLBACK, created_days=5, resolved_days=3)
    facts = why_facts(db_session, _came_back(past), finding=_latency_finding(db_session), change_config=None)

    reasons = write_why(_ai([
        "The fix was a rollback, and the retry loop may still be in the code.",
        "Version v2.9 may have brought it back.",
        "The team definitely forgot to restart it.",
    ]), facts)

    assert reasons == ["The fix was a rollback, and the retry loop may still be in the code."]
    assert ROLLBACK["fix"] in facts.text and "came back 3 days later" in facts.text
    assert {source["label"] for source in facts.sources} >= {f"Case #{past.id}", f"Case #{past.id} fix"}


def test_with_no_hint_the_model_is_not_asked_to_guess(db_session, memory, monkeypatch):
    past = _case(db_session, memory, monkeypatch, "pool_a", spec=POOL_A, created_days=5, resolved_days=3)
    came_back = _came_back(past).model_copy(update={"fix": POOL_A["fix"], "still_open": None})
    facts = why_facts(db_session, came_back, finding=None, change_config=None)
    client = _ScriptedClient(response_text=json.dumps({"reasons": ["The fix may not have been fully rolled out."]}))

    assert write_why(OptionalAIServices(client=client, structured=None), facts) == []
    assert client.calls == []


def test_hints_name_only_what_the_case_shows(db_session, memory, monkeypatch):
    past = _case(db_session, memory, monkeypatch, "rollback", spec=ROLLBACK, created_days=5, resolved_days=3)

    hints = [line for line in why_facts(db_session, _came_back(past), finding=None, change_config=None).lines if line.startswith("Hint: ")]

    assert hints == [
        "Hint: the past case said this was still open: fix the retry loop.",
        "Hint: the past fix (Rolled back to v2.2.) stops a problem but can leave its cause in place.",
    ]


def test_a_deploy_claim_without_a_matched_deploy_is_dropped(db_session, memory, monkeypatch):
    past = _case(db_session, memory, monkeypatch, "rollback", spec=ROLLBACK, created_days=5, resolved_days=3)
    facts = why_facts(db_session, _came_back(past), finding=None, change_config=None)

    reasons = write_why(_ai(["A new deploy may have brought it back.", "the rollback may have left the retry loop in place."]), facts)

    assert reasons == ["The rollback may have left the retry loop in place."]


def test_a_broken_reply_is_a_failure_not_an_answer(db_session, memory, monkeypatch):
    past = _case(db_session, memory, monkeypatch, "rollback", spec=ROLLBACK, created_days=5, resolved_days=3)
    facts = why_facts(db_session, _came_back(past), finding=None, change_config=None)
    broken = OptionalAIServices(client=_ScriptedClient(response_text="not json"), structured=None)

    assert write_why(broken, facts) is None


def test_the_why_endpoints(client, db_session, monkeypatch):
    past = _add_case(db_session, "db_pool")
    new = _add_case(db_session, "db_pool", resolved=False)
    overrides = client.app.dependency_overrides

    assert client.post(f"/api/cases/{new.id}/fix-came-back/why").json()["reason_code"] == "ai_off"

    overrides[assistant_module.get_assistant] = lambda: _assistant_with(_ScriptedClient(response_text=json.dumps({"reasons": []})))
    monkeypatch.setattr(memory_module, "case_fix_came_back", lambda *args: CaseFixCameBackResponse(case_id=new.id, available=True))
    assert client.post(f"/api/cases/{new.id}/fix-came-back/why").json()["reason_code"] == "not_enough"

    monkeypatch.setattr(memory_module, "case_fix_came_back", lambda *args: CaseFixCameBackResponse(case_id=new.id, available=True, came_back=_came_back(past)))
    assert client.post(f"/api/cases/{new.id}/fix-came-back/why").json()["reason"] == "Not enough in the cases to say why."

    reason = f"The same cause may be back: {past.root_cause_summary}"
    overrides[assistant_module.get_assistant] = lambda: _assistant_with(_ScriptedClient(response_text=json.dumps({"reasons": [reason]})))
    body = client.post(f"/api/cases/{new.id}/fix-came-back/why").json()
    assert body["available"] and body["reasons"] == [reason], body

    # A finding with memory off has nothing to explain.
    assert client.post(f"/api/findings/{new.finding_id}/fix-came-back/why").json()["reason_code"] == "not_enough"
    assert client.post("/api/findings/999/fix-came-back/why").status_code == 404
