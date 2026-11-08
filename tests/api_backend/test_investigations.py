"""Guided investigation (backend/app/investigation/): a scripted model asks for checks, faked
Prometheus answers them, and each stop rule ends the round the way docs/investigate.md says.

Rounds run in place (service.submit), the model is scripted (no network) and Prometheus is faked on
PrometheusQueryService, so the real loop, tools, evidence check and API run end to end.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.tool_calls import ToolCall, ToolRequest, ToolResponse
from backend.app.config import PrometheusConnectionConfig, PrometheusConnections
from backend.app.investigation import context as context_module
from backend.app.investigation import loop, service
from backend.app.investigation.tools import ToolBox, summarise_series
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, ChangeEventEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.prometheus_service import PrometheusQueryService

STARTING_CALLS = ToolBox.starting_calls
START = datetime(2026, 11, 5, 21, 30, tzinfo=timezone.utc)
CHANGE = datetime(2026, 11, 5, 22, 30, tzinfo=timezone.utc)


def _as(role: str, login: str = "priya") -> dict[str, str]:
    return {"X-Grafana-Context": json.dumps({"UserID": 3, "Login": login, "Email": f"{login}@example.com", "OrgRole": role, "IsAnonymous": False})}


class ScriptedModel:
    """Answers each turn from a script: a list of tool calls, a final answer (dict), or an exception."""

    model = "scripted"

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.requests: list[ToolRequest] = []

    def generate(self, request):  # pragma: no cover - investigations only use tools
        raise AssertionError("generate() should not be called")

    def generate_with_tools(self, request: ToolRequest) -> ToolResponse:
        self.requests.append(request)
        item = self.script.pop(0) if self.script else {"summary": "Out of script.", "ending": "nothing_found", "steps": []}
        if isinstance(item, Exception):
            raise item
        if isinstance(item, list):
            return ToolResponse(content="", tool_calls=tuple(item), model="scripted", provider="scripted")
        if isinstance(item, str):
            return ToolResponse(content=item, model="scripted", provider="scripted")
        return ToolResponse(content=json.dumps(item), model="scripted", provider="scripted")


def _query(n: int, promql: str | None = None, purpose: str = "check") -> ToolCall:
    return ToolCall(id=f"t{n}", name="query_range", arguments={"promql": promql or f"metric_{n}", "purpose": purpose})


def _series(labels: dict, before: float, after: float) -> dict:
    values = []
    for minute in range(0, 120, 5):
        moment = START + timedelta(minutes=minute)
        values.append([moment.timestamp(), str(before if moment < CHANGE else after)])
    return {"metric": labels, "values": values}


@pytest.fixture()
def prometheus(monkeypatch):
    """Faked Prometheus: every range query returns three pods that jumped at 22:30. The starting
    checks are off, so the model's checks are c1, c2...; the starting-check tests turn them on."""
    calls: dict[str, list] = {"queries": []}
    connection = PrometheusConnectionConfig(id="default", name="prod-metrics", base_url="http://prometheus:9090")
    monkeypatch.setattr(context_module, "get_prometheus_connections", lambda: PrometheusConnections(connections=[connection], default_id="default"))
    monkeypatch.setattr(service, "get_prometheus_connections", lambda: PrometheusConnections(connections=[connection], default_id="default"))

    def query_result(self, query, **kwargs):
        calls["queries"].append(query)
        if "down" in query:
            raise HTTPException(status_code=503, detail="Prometheus connection failed")
        return [_series({"pod": f"checkout-{index}"}, 0.2, 1.8) for index in range(3)]

    monkeypatch.setattr(PrometheusQueryService, "query_result", query_result)
    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", lambda self, selector, **kw: [{"__name__": "db_client_wait_seconds", "service": "checkout", "db_name": "checkout-db"}])
    monkeypatch.setattr(PrometheusQueryService, "label_values", lambda self, label, matchers, **kw: ["checkout-0", "checkout-1", "checkout-2"])
    monkeypatch.setattr(ToolBox, "starting_calls", lambda self: [])
    return calls


@pytest.fixture()
def run_inline(monkeypatch):
    monkeypatch.setattr(service, "submit", lambda task: task())


def _use(monkeypatch, model) -> None:
    monkeypatch.setattr(service, "ai_client", lambda: model)


def _finding(source_type: str = "prometheus", service_name: str = "checkout", run_id: str = "run-inv-1") -> int:
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(
            id=run_id, source_type=source_type, provider="prometheus", service=service_name, metric_name="http_request_duration_seconds",
            start_time=START, end_time=START + timedelta(hours=2), sample_count=24, status="completed",
            connection_id="default" if source_type == "prometheus" else None,
            promql='histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="checkout"}[5m])))' if source_type == "prometheus" else None,
        ))
        finding = FindingEntity(
            analysis_run_id=run_id, service=service_name, metric_name="http_request_duration_seconds",
            title="Checkout latency jumped", summary="Latency went from about 0.2 s to about 1.8 s.",
            category="behavior_change", health_status="critical", importance_score=0.9, investigation_priority=1,
            signal_ids=[], comparison_json={}, event_start=CHANGE, event_end=START + timedelta(hours=2), ongoing=True,
        )
        db.add(finding)
        db.add(ChangeEventEntity(service=service_name, event_type="config", timestamp=CHANGE - timedelta(minutes=3), description="pool size 50 -> 10"))
        db.commit()
        return finding.id


FINAL = {
    "summary": "The root cause is checkout-db: checkout waits for it from 22:28.",
    "ending": "found",
    "question": None,
    "steps": [
        {"title": "Is it one bad pod?", "kind": "checked", "status": "ruled_out", "why": "Quick to rule out.", "result": "All 3 pods jumped.", "evidence": ["c1"]},
        {"title": "Waiting for checkout-db", "kind": "checked", "status": "worth_a_look", "why": "DB wait rose first.", "result": "Wait rose at 22:28.", "evidence": ["c2"]},
        {"title": "Traffic jumped", "kind": "checked", "status": "ruled_out", "result": "Made up.", "evidence": ["c9"]},
        {"title": "Check the pool size change", "kind": "your_step", "status": "todo", "why": "Config changed at 22:27.", "result": "Who changed it?"},
    ],
}


def test_an_investigation_runs_its_checks_and_keeps_only_claims_it_can_back(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel([_query(1, 'sum by (pod) (rate(x[5m]))', "Is it one pod?")], [_query(2, "db_wait", "Waiting for the DB?")], FINAL)
    _use(monkeypatch, model)

    started = client.post("/api/investigations", json={"finding_id": finding_id, "note": "We moved checkout-db tonight."}, headers=_as("Editor"))
    assert started.status_code == 200
    body = client.get(f"/api/investigations/{started.json()['id']}").json()

    assert (body["status"], body["ending"], body["started_by"]) == ("done", "found", "priya")
    assert body["summary"] == "a likely cause is checkout-db: checkout waits for it from 22:28."
    assert [check["ref"] for check in body["checks"]] == ["c1", "c2"]
    assert body["checks"][0]["purpose"] == "Is it one pod?" and body["checks"][0]["query"] == "sum by (pod) (rate(x[5m]))"
    assert 'pod="checkout-0"' in body["checks"][0]["result"] and "before 22:30 about 0.2, after about 1.8" in body["checks"][0]["result"]
    steps = {step["title"]: step for step in body["steps"]}
    assert steps["Waiting for checkout-db"]["evidence"] == ["c2"] and not steps["Waiting for checkout-db"]["unverified"]
    assert steps["Traffic jumped"]["unverified"] is True and steps["Traffic jumped"]["evidence"] == []
    assert steps["Check the pool size change"]["kind"] == "your_step"

    opening = model.requests[0].messages[1].content
    assert "Service: checkout" in opening and "pool size 50 -> 10" in opening and "We moved checkout-db tonight." in opening
    assert "histogram_quantile(0.95" in opening
    assert {spec.name for spec in model.requests[0].tools} == {"list_series", "label_values", "query_range", "changes", "similar_cases", "findings_for"}


def test_unticked_sources_are_left_out(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel({"summary": "Nothing found.", "ending": "nothing_found", "steps": []})
    _use(monkeypatch, model)

    client.post("/api/investigations", json={"finding_id": finding_id, "skipped_sources": ["changes", "cases"]}, headers=_as("Editor"))

    assert {spec.name for spec in model.requests[0].tools} == {"list_series", "label_values", "query_range", "findings_for"}
    assert "pool size" not in model.requests[0].messages[1].content


def test_a_finding_from_an_uploaded_file_cannot_be_investigated(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding(source_type="csv", run_id="run-csv")
    _use(monkeypatch, ScriptedModel())

    info = client.get(f"/api/investigations/start-info?finding_id={finding_id}").json()
    refused = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor"))

    assert info["eligible"] is False and "uploaded file" in info["reason"]
    assert refused.status_code == 400 and "uploaded file" in refused.json()["detail"]


def test_with_ai_off_the_dialog_says_so_and_nothing_starts(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    monkeypatch.setattr(service, "ai_client", lambda: None)

    assert client.get(f"/api/investigations/start-info?finding_id={finding_id}").json()["ai_on"] is False
    assert client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).status_code == 400


def test_viewers_read_investigations_but_cannot_start_one(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    _use(monkeypatch, ScriptedModel())

    assert client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Viewer")).status_code == 403
    assert client.get(f"/api/investigations?finding_id={finding_id}", headers=_as("Viewer")).status_code == 200


def test_the_check_budget_pauses_the_round_and_the_model_writes_up(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    many = [[_query(n), _query(n + 100)] for n in range(1, 9)]
    wrap_up = {"summary": "Look at the DB.", "ending": "found", "steps": [{"title": "DB wait", "kind": "checked", "status": "worth_a_look", "evidence": ["c3"]}]}
    model = ScriptedModel(*many, wrap_up)
    _use(monkeypatch, model)
    monkeypatch.setattr(PrometheusQueryService, "query_result", lambda self, query, **kw: [_series({"query": query}, 1, 2)])

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"]) == ("paused", "budget")
    assert body["ending_detail"] == f"{loop.FIRST_BUDGET} of {loop.FIRST_BUDGET} checks used."
    assert len(body["checks"]) == loop.FIRST_BUDGET
    assert body["steps"][0]["title"] == "DB wait"
    assert "Stop checking now" in model.requests[-1].messages[-1].content


def test_checks_that_find_nothing_new_end_the_round(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    same = _query(1, "db_wait")
    model = ScriptedModel([same], [same], [same], [same], {"summary": "Look at the DB.", "ending": "found", "steps": []})
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"], body["ending_detail"]) == ("done", "no_progress", None)
    assert len(body["checks"]) == 1 and len(prometheus["queries"]) == 1


def test_prometheus_down_twice_stops_the_round(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel([_query(1, "down_a")], [_query(2, "down_b")], {"summary": "Couldn't check.", "ending": "nothing_found", "steps": []})
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"]) == ("stopped", "source_down")
    assert [check["ok"] for check in body["checks"]] == [False, False]


def test_two_ai_failures_fail_the_round_and_keep_the_checks_as_steps(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel([_query(1, "db_wait", "Waiting for the DB?")], LLMRequestError("timeout"), LLMRequestError("timeout"))
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"]) == ("failed", "ai_failed")
    assert [(step["title"], step["why"], step["evidence"]) for step in body["steps"]] == [("Metric query", "Waiting for the DB?", ["c1"])]


def test_a_reply_that_is_not_the_json_gets_one_more_try(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel("I think it's the database.", {"summary": "Look at the DB.", "ending": "waiting", "question": "Did anyone change the pool size?", "steps": []})
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"], body["question"]) == ("done", "waiting", "Did anyone change the pool size?")
    assert model.requests[1].messages[-1].content == loop.REPAIR


def test_stop_ends_the_round_after_the_current_check(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel([_query(1, "db_wait", "Waiting for the DB?")], [_query(2)])
    _use(monkeypatch, model)

    def query_then_stop(self, query, **kwargs):
        with get_session_local()() as db:
            from backend.app.models.entities import InvestigationEntity

            for row in db.query(InvestigationEntity).all():
                row.stop_requested = True
            db.commit()
        return [_series({}, 1, 2)]

    monkeypatch.setattr(PrometheusQueryService, "query_result", query_then_stop)
    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"]) == ("stopped", "stopped")
    assert len(body["checks"]) == 1 and len(model.requests) == 1


def test_marks_and_notes_go_back_to_the_model_and_new_steps_are_added(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    model = ScriptedModel([_query(1), _query(2)], FINAL)
    _use(monkeypatch, model)
    first = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{first['id']}").json()
    db_step = next(step for step in body["steps"] if step["title"] == "Waiting for checkout-db")

    marked = client.patch(
        f"/api/investigations/{body['id']}/steps/{db_step['id']}",
        json={"mark": "ruled_out", "note": "The DB move finished at 18:00."},
        headers=_as("Editor", "sam"),
    ).json()
    assert next(step for step in marked["steps"] if step["id"] == db_step["id"])["marked_by"] == "sam"

    model.script = [[_query(3, "pool_max")], {"summary": "The pool shrank at 22:27.", "ending": "waiting", "question": "Who changed the pool size?",
                    "steps": [{"title": "Pool size dropped", "kind": "checked", "status": "worth_a_look", "evidence": ["c3"]}]}]
    client.post(f"/api/investigations/{body['id']}/continue", json={"message": "DB looks fine."}, headers=_as("Editor"))
    after = client.get(f"/api/investigations/{body['id']}").json()

    told = model.requests[-2].messages[-1].content
    assert 'Step "Waiting for checkout-db": ruled it out. Note: "The DB move finished at 18:00."' in told
    assert 'The engineer says: "DB looks fine."' in told
    assert (after["round"], after["check_budget"], after["ending"]) == (2, loop.LATER_BUDGET, "waiting")
    assert after["steps"][-1]["title"] == "Pool size dropped" and after["steps"][-1]["round"] == 2
    assert len(after["steps"]) == len(body["steps"]) + 1


def test_saving_to_a_case_adds_what_people_marked_as_a_note(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    _use(monkeypatch, ScriptedModel([_query(1), _query(2)], FINAL))
    investigation = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{investigation['id']}").json()
    db_step = next(step for step in body["steps"] if step["title"] == "Waiting for checkout-db")
    client.patch(f"/api/investigations/{body['id']}/steps/{db_step['id']}", json={"mark": "found", "note": "analytics-export holds 14 connections"}, headers=_as("Editor"))
    case_id = client.post(f"/api/cases/findings/{finding_id}/create", headers=_as("Editor")).json()["case_id"]

    saved = client.post(f"/api/investigations/{body['id']}/case", json={"case_id": case_id}, headers=_as("Editor")).json()

    assert saved["case_id"] == case_id
    assert client.get(f"/api/investigations?case_id={case_id}").json()[0]["id"] == body["id"]
    with get_session_local()() as db:
        case = db.get(OperationalCaseEntity, case_id)
        note = case.investigation_notes[-1]["note"]
        assert case.investigation_status == "in_progress"
    assert "Found something: Waiting for checkout-db. Wait rose at 22:28." in note
    assert 'Note: "analytics-export holds 14 connections"' in note
    assert "Ruled out: Is it one bad pod?." in note
    assert "Traffic jumped" not in note


def test_a_note_marked_always_true_is_saved_for_the_service(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    _use(monkeypatch, ScriptedModel({"summary": "x", "ending": "nothing_found", "steps": []}))

    client.post("/api/investigations", json={"finding_id": finding_id, "note": "Reports run at 02:00.", "save_note": True}, headers=_as("Editor", "sam"))

    behaviours = client.get("/api/service-notes/checkout").json()["behaviours"]
    assert [(item["text"], item["by"]) for item in behaviours] == [("Reports run at 02:00.", "sam")]


def test_steps_claiming_a_case_they_were_not_shown_are_unverified() -> None:
    final = {"steps": [
        {"title": "Same as case #204", "kind": "from_history", "status": "todo", "evidence": ["case #204"]},
        {"title": "Same as case #999", "kind": "from_history", "status": "todo", "evidence": ["case #999"]},
        {"title": "x", "kind": "weird", "status": "odd"},
    ]}

    steps = loop.check_steps(final, refs={"c1"}, cases={204})

    assert [(step["evidence"], step["unverified"]) for step in steps[:2]] == [(["case #204"], False), ([], True)]
    assert (steps[2]["kind"], steps[2]["status"]) == ("your_step", "todo")


def _toolbox(db, finding_id: int):
    from backend.app.investigation.context import finding_context
    from backend.app.investigation.tools import ToolBox

    finding = db.get(FindingEntity, finding_id)
    return ToolBox(db, finding_context(db, finding), PrometheusQueryService(None), ["service", "app"])


def test_list_series_filters_by_name_and_findings_for_says_when_a_service_is_not_watched(client, prometheus) -> None:
    finding_id = _finding()
    with get_session_local()() as db:
        tools = _toolbox(db, finding_id)
        listed = tools.run(ToolCall("a", "list_series", {"match": "db|pool", "purpose": "find DB metrics"}))
        none = tools.run(ToolCall("b", "list_series", {"match": "kafka", "purpose": "queue?"}))
        others = tools.run(ToolCall("c", "findings_for", {"services": ["checkout-db"], "purpose": "DB findings?"}))
        unknown = tools.run(ToolCall("d", "drop_table", {}))

    assert listed.ok and "db_client_wait_seconds (labels: db_name)" in listed.text and listed.purpose == "find DB metrics"
    assert "No metric of checkout matches 'kafka'" in none.text
    assert "never had a finding on checkout-db" in others.text
    assert not unknown.ok and "no tool called 'drop_table'" in unknown.text


def test_the_default_window_shows_the_change_even_for_an_old_problem_still_going_on(client, prometheus) -> None:
    finding_id = _finding()
    with get_session_local()() as db:
        tools = _toolbox(db, finding_id)
        start, end = tools._window({})
        wide = tools._window({"start": "2026-11-01T00:00:00Z", "end": "2026-11-08T00:00:00Z"})

    assert start == CHANGE - timedelta(hours=1) and end == CHANGE + timedelta(hours=6)
    assert wide[1] - wide[0] == timedelta(hours=12) and wide[0] == datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_every_investigation_starts_from_the_finding_query_and_its_scrape_targets(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    monkeypatch.setattr(ToolBox, "starting_calls", STARTING_CALLS)
    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", lambda self, selector, **kw: [{"__name__": "http_requests_total", "service": "checkout", "job": "checkout-api"}])
    model = ScriptedModel([_query(1, "db_wait", "Waiting for the DB?")], {"summary": "Look at the DB.", "ending": "found", "steps": []})
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert [(check["ref"], check["query"]) for check in body["checks"]] == [
        ("c1", 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="checkout"}[5m])))'),
        ("c2", 'sum by (job) (up{job="checkout-api"})'),
        ("c3", 'sum by (job) (scrape_samples_scraped{job="checkout-api"})'),
        ("c4", "db_wait"),
    ]
    assert body["checks_used"] == 1
    opening = model.requests[0].messages[1].content
    assert "Checks already run for you (use these exact metric names" in opening and "[c2] Were its scrape targets up?" in opening


def test_a_model_that_puts_its_answer_in_a_tool_call_has_answered(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    tucked = ToolCall("t9", "changes", {"summary": "Look at the DB.", "ending": "found", "steps": [
        {"title": "Waiting for checkout-db", "kind": "checked", "status": "worth_a_look", "evidence": ["c1"]}]})
    model = ScriptedModel([_query(1, "db_wait")], [tucked])
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["status"], body["ending"], body["summary"]) == ("done", "found", "Look at the DB.")
    assert [check["tool"] for check in body["checks"]] == ["query_range"]
    assert [step["title"] for step in body["steps"]] == ["Waiting for checkout-db"]


def test_the_write_up_can_also_come_as_a_tool_call(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    same = _query(1, "db_wait")
    tucked = ToolCall("t9", "changes", {"final": {"summary": "Look at the DB.", "ending": "nothing_found", "steps": [
        {"title": "DB wait", "kind": "checked", "status": "ruled_out", "evidence": ["c1"]}]}})
    model = ScriptedModel([same], [same], [same], [same], [tucked])
    _use(monkeypatch, model)

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert (body["ending"], body["ending_detail"], body["summary"]) == ("no_progress", None, "Look at the DB.")
    assert [step["title"] for step in body["steps"]] == ["DB wait"]


def test_without_a_write_up_each_distinct_check_is_one_step(client, prometheus, run_inline, monkeypatch) -> None:
    finding_id = _finding()
    deploys = [ToolCall(f"d{n}", "changes", {"start": f"2026-11-05T2{n}:00:00Z", "purpose": "Any deploy?"}) for n in range(1, 5)]
    model = ScriptedModel([_query(1, "db_wait", "Waiting for the DB?")], *[[call] for call in deploys], "not json")
    _use(monkeypatch, model)
    from backend.app.investigation import tools as tools_module
    monkeypatch.setattr(tools_module, "change_rows", lambda *a, **kw: [])
    monkeypatch.setattr(tools_module, "_hhmm", lambda moment: "22:00")

    body = client.post("/api/investigations", json={"finding_id": finding_id}, headers=_as("Editor")).json()
    body = client.get(f"/api/investigations/{body['id']}").json()

    assert body["ending"] == "no_progress" and body["ending_detail"] == loop.FELL_BACK
    assert [(step["title"], step["status"], step["evidence"]) for step in body["steps"]] == [
        ("Metric query", "todo", ["c1"]),
        ("Deploys and changes", "ruled_out", ["c2", "c3", "c4", "c5"]),
    ]


def test_a_series_summary_says_where_data_is_missing() -> None:
    values = [[(START + timedelta(minutes=minute)).timestamp(), "1"] for minute in range(0, 120) if not 50 <= minute < 56]

    line = summarise_series({"metric": {"pod": "a"}, "values": values}, None)

    assert line.endswith("; no data 22:19–22:26.")


def _without_saved_query(finding_id: int) -> None:
    with get_session_local()() as db:
        db.get(AnalysisRunEntity, db.get(FindingEntity, finding_id).analysis_run_id).promql = None
        db.commit()


def test_a_finding_without_its_query_starts_from_its_metric_and_service_label(client, prometheus, monkeypatch) -> None:
    finding_id = _finding()
    _without_saved_query(finding_id)
    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", lambda self, selector, **kw: [
        {"__name__": "http_request_duration_seconds", "app": "checkout", "job": "checkout-api"},
        {"__name__": "db_client_wait_seconds", "app": "checkout", "job": "checkout-api"},
    ] if 'app="checkout"' in selector else [])

    with get_session_local()() as db:
        calls = STARTING_CALLS(_toolbox(db, finding_id))

    assert (calls[0].arguments["promql"], calls[0].arguments["purpose"]) == ('http_request_duration_seconds{app="checkout"}', "The metric that found it")
    assert len(calls) == 3


def test_a_metric_prometheus_does_not_have_is_not_guessed(client, prometheus, monkeypatch) -> None:
    finding_id = _finding()
    _without_saved_query(finding_id)
    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", lambda self, selector, **kw: [{"__name__": "http_requests_total", "service": "checkout", "job": "checkout-api"}])

    with get_session_local()() as db:
        calls = STARTING_CALLS(_toolbox(db, finding_id))

    assert [call.arguments["purpose"] for call in calls] == ["Were its scrape targets up?", "Did Prometheus get as many samples as usual?"]
