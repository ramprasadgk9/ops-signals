"""What a team knows about a service: saved by Editors, read by everyone, and dependencies suggested
from labels on the service's own series (backend/app/services/service_notes.py)."""

from __future__ import annotations

import json

from backend.app.services import service_notes
from backend.app.services.prometheus_service import PrometheusQueryService


def _as(role: str, login: str = "sam") -> dict[str, str]:
    return {"X-Grafana-Context": json.dumps({"UserID": 3, "Login": login, "Email": f"{login}@example.com", "OrgRole": role, "IsAnonymous": False})}


NOTE = {
    "depends_on": [{"name": "payments-db", "kind": "database"}, {"name": "card-provider", "kind": "outside"}, {"name": "payments-db", "kind": "database"}],
    "behaviours": [{"text": "Traffic halves on Sundays. That's normal."}, {"text": "   "}],
    "owner": "payments team",
    "channel": "#payments-oncall",
}


def test_a_service_nobody_described_has_empty_notes(client) -> None:
    body = client.get("/api/service-notes/payment").json()

    assert body["exists"] is False and body["depends_on"] == [] and body["behaviours"] == []


def test_an_editor_saves_notes_and_each_line_keeps_who_wrote_it(client) -> None:
    saved = client.put("/api/service-notes/payment", json=NOTE, headers=_as("Editor", "priya")).json()

    assert saved["exists"] is True and saved["updated_by"] == "priya"
    assert [item["name"] for item in saved["depends_on"]] == ["payments-db", "card-provider"]
    assert [(item["text"], item["by"]) for item in saved["behaviours"]] == [("Traffic halves on Sundays. That's normal.", "priya")]

    # Sam edits later: Priya's line keeps her name.
    later = {**NOTE, "behaviours": [*saved["behaviours"], {"text": "Reports run at 02:00."}]}
    again = client.put("/api/service-notes/payment", json=later, headers=_as("Editor", "sam")).json()
    assert [item["by"] for item in again["behaviours"]] == ["priya", "sam"]
    assert client.get("/api/service-notes").json()[0]["service"] == "payment"


def test_a_viewer_reads_notes_but_cannot_change_them(client) -> None:
    client.put("/api/service-notes/payment", json=NOTE, headers=_as("Editor"))

    assert client.get("/api/service-notes/payment", headers=_as("Viewer")).status_code == 200
    assert client.put("/api/service-notes/payment", json=NOTE, headers=_as("Viewer")).status_code == 403


def test_dependencies_are_suggested_from_labels_on_the_services_own_series(monkeypatch) -> None:
    asked: list[str] = []

    def series(self, selector, **_):
        asked.append(selector)
        if selector.startswith("{service="):
            return []
        return [
            {"__name__": "db_client_wait_seconds", "app": "payment", "db_name": "payments-db"},
            {"__name__": "http_client_seconds", "app": "payment", "peer_service": "fraud-check"},
            {"__name__": "kafka_lag", "app": "payment", "topic": "orders", "consumergroup": "payment"},
            {"__name__": "http_client_seconds", "app": "payment", "peer_service": "card-provider"},
        ]

    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", series)
    suggestions = service_notes.suggest_dependencies(
        PrometheusQueryService(None), "payment", ["service", "app"], known={"card-provider"}
    )

    assert asked == ['{service="payment"}', '{app="payment"}']
    assert [(item["name"], item["kind"]) for item in suggestions] == [("fraud-check", "service"), ("payments-db", "database"), ("orders", "queue")]
    assert suggestions[1]["label"] == 'db_name="payments-db"'


def test_suggestions_are_empty_when_prometheus_fails(monkeypatch) -> None:
    def broken(self, selector, **_):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(PrometheusQueryService, "direct_scoped_series", broken)

    assert service_notes.suggest_dependencies(PrometheusQueryService(None), "payment", ["service"], known=set()) == []


def test_notes_become_prompt_lines() -> None:
    text = service_notes.notes_text({
        "depends_on": [{"name": "payments-db", "kind": "database"}],
        "behaviours": [{"text": "Reports hold DB connections.", "case_id": 204}, {"text": "Sundays are quiet.", "by": "sam"}],
        "owner": "payments team",
    })

    assert text == (
        "Depends on: payments-db (database).\n"
        'Known behaviour (case #204): "Reports hold DB connections."\n'
        'Known behaviour (sam): "Sundays are quiet."\n'
        "Owner: payments team."
    )
    assert service_notes.notes_text({"depends_on": [], "behaviours": []}) is None
