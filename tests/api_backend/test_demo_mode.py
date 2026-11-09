"""Demo mode (backend/app/demo.py, backend/app/api/demo.py): what visitors to the hosted demo can't do,
the countdown, and the sample files New Analysis offers instead of uploads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import demo
from backend.app.api.ingestion import PreviewPipelineStore
from backend.app.config import MemoryConfig
from backend.app.demo import DemoConfig, demo_refusal, next_reset
from backend.app.main import create_app
from intelligence.pipeline import SignalPipeline

VISITOR = {"X-Forwarded-For": "203.0.113.7"}


@pytest.fixture()
def demo_client(monkeypatch):
    monkeypatch.setenv("OPS_SIGNALS_DEMO_MODE", "true")
    monkeypatch.setenv("OPS_SIGNALS_DEMO_RESET_HOURS", "2")
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            yield client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/events"),
        ("POST", "/api/integrations/alertmanager"),
        ("POST", "/api/otlp/v1/metrics"),
        ("POST", "/api/ingestion/csv-run"),
        ("POST", "/api/autonomous/policies"),
        ("PATCH", "/api/autonomous/policies/abc/status"),
        ("POST", "/api/cases/3/ticket/create"),
        ("POST", "/api/behavior-definitions/save-to-pack"),
        ("POST", "/api/behavior-definitions/suggestions/mine"),
        ("POST", "/api/analyzer-labs/drafts"),
        ("POST", "/api/testing/reset-operational-data"),
        ("POST", "/api/ai/test"),
        ("DELETE", "/api/cases/3/memory"),
        ("GET", "/api/setup/check"),
        ("GET", "/api/case-imports"),
    ],
)
def test_what_a_visitor_cant_do(method: str, path: str) -> None:
    assert demo_refusal(method, path).startswith("Turned off in the demo")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/findings"),
        ("GET", "/api/alerts"),
        ("POST", "/api/cases/findings/12/create"),
        ("PATCH", "/api/cases/3/rca"),
        ("POST", "/api/cases/3/rca/suggest"),
        ("POST", "/api/findings/12/feedback"),
        ("POST", "/api/assistant/chat"),
        ("POST", "/api/ingestion/prometheus-run"),
        ("POST", "/api/prometheus/preview"),
        ("POST", "/api/autonomous/run-once"),
        ("POST", "/api/demo/samples/sudden-jump"),
        ("POST", "/api/overview/handoff/note"),
    ],
)
def test_what_a_visitor_can_do(method: str, path: str) -> None:
    assert demo_refusal(method, path) is None


def test_a_visitor_is_refused_with_the_reason(demo_client) -> None:
    response = demo_client.post("/api/events", json=[], headers=VISITOR)
    assert response.status_code == 403
    assert response.json()["detail"] == "Turned off in the demo: only the demo's own services send alerts, metrics and deploys here."


def test_the_demos_own_services_are_not_refused(demo_client) -> None:
    # The seeder, Alertmanager and the OTLP sender call the backend directly, not through the proxy.
    assert demo_client.post("/api/events", json=[]).status_code != 403
    assert demo_client.get("/api/setup/check").status_code == 200


def test_nothing_is_refused_when_demo_mode_is_off(monkeypatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_DEMO_MODE", raising=False)
    monkeypatch.delenv("OPS_SIGNALS_DEMO_TOUR", raising=False)
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            assert client.get("/api/setup/check", headers=VISITOR).status_code == 200
            assert client.get("/api/demo").json() == {
                "enabled": False, "tour": False, "resets_at": None, "reset_hours": None, "run_yourself_url": None, "ai": "off", "ai_model": None, "samples": [],
            }
            assert client.post("/api/demo/samples/sudden-jump").status_code == 404


def test_the_tour_alone_shows_the_guide_and_leaves_everything_open(monkeypatch) -> None:
    # The local demo (docker-compose.demo.yml): Things to try, without the banner or view-only settings.
    monkeypatch.delenv("OPS_SIGNALS_DEMO_MODE", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_DEMO_TOUR", "true")
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            body = client.get("/api/demo", headers=VISITOR).json()
            assert body["enabled"] is False
            assert body["tour"] is True
            assert client.get("/api/setup/check", headers=VISITOR).status_code == 200


@pytest.mark.parametrize("value", ["false", "0", ""])
def test_the_tour_can_be_turned_off(monkeypatch, value: str) -> None:
    monkeypatch.delenv("OPS_SIGNALS_DEMO_MODE", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_DEMO_TOUR", value)
    assert demo.get_demo_config().tour is False


def test_the_ui_learns_the_reset_time_ai_mode_and_samples(demo_client) -> None:
    body = demo_client.get("/api/demo", headers=VISITOR).json()

    assert body["enabled"] is True
    assert body["tour"] is True
    assert body["reset_hours"] == 2
    assert datetime.fromisoformat(body["resets_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
    assert body["ai"] == "off"
    assert body["run_yourself_url"].endswith("#try-it-in-one-command")
    assert [sample["id"] for sample in body["samples"]] == ["sudden-jump", "slow-climb", "short-spikes", "repeating"]
    assert all(sample["service"].startswith("sample-") for sample in body["samples"])


def test_a_sample_is_analyzed_like_an_upload(demo_client) -> None:
    # Pipeline store swapped out: a bare SignalPipeline writes to the database in config.yaml.
    with patch("backend.app.api.ingestion.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
        response = demo_client.post("/api/demo/samples/slow-climb", headers=VISITOR)

    assert response.status_code == 200
    body = response.json()
    assert (body["file_name"], body["service"], body["metric_name"], body["sample_count"]) == ("slow-climb.csv", "sample-search", "memory_usage", 120)


def test_an_unknown_sample_is_not_found(demo_client) -> None:
    assert demo_client.post("/api/demo/samples/../../etc/passwd", headers=VISITOR).status_code == 404
    assert demo_client.post("/api/demo/samples/nope", headers=VISITOR).status_code == 404


def test_the_local_demo_analyzes_samples_too(monkeypatch) -> None:
    # The local demo (the tour on, not demo mode) offers the same one-click samples.
    monkeypatch.delenv("OPS_SIGNALS_DEMO_MODE", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_DEMO_TOUR", "true")
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            with patch("backend.app.api.ingestion.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
                response = client.post("/api/demo/samples/sudden-jump", headers=VISITOR)
    assert response.status_code == 200
    assert response.json()["sample_count"] == 120


def test_everyone_can_see_and_download_the_sample_files(monkeypatch) -> None:
    # Not only in the demo: they show anyone what a CSV upload looks like.
    monkeypatch.delenv("OPS_SIGNALS_DEMO_MODE", raising=False)
    monkeypatch.delenv("OPS_SIGNALS_DEMO_TOUR", raising=False)
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            files = client.get("/api/samples", headers=VISITOR).json()
            assert [item["file"] for item in files] == ["sudden-jump.csv", "slow-climb.csv", "short-spikes.csv", "repeating.csv"]
            first = files[0]
            assert (first["rows"], first["interval"]) == (120, "5m")
            assert first["preview"][0] == "timestamp,metric_name,value,service,env"
            assert len(first["preview"]) == 4

            download = client.get("/api/samples/sudden-jump.csv", headers=VISITOR)
            assert download.status_code == 200
            assert download.headers["content-type"].startswith("text/csv")
            assert download.headers["content-disposition"] == 'attachment; filename="sudden-jump.csv"'
            assert download.text.splitlines()[:4] == first["preview"]

            # Only the files the manifest lists.
            assert client.get("/api/samples/samples.yml", headers=VISITOR).status_code == 404
            assert client.get("/api/samples/..%2F..%2Fconfig.yaml", headers=VISITOR).status_code == 404


def test_the_next_reset_is_the_first_period_still_ahead(monkeypatch) -> None:
    started = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(demo, "_STARTED_AT", started)
    config = DemoConfig(enabled=True, reset_hours=2)

    assert next_reset(config, now=started + timedelta(minutes=30)) == started + timedelta(hours=2)
    # Missed a reset (the job didn't restart it): the next period, not a time in the past.
    assert next_reset(config, now=started + timedelta(hours=2, minutes=5)) == started + timedelta(hours=4)
    assert next_reset(DemoConfig(enabled=True, reset_hours=0)) is None
    assert next_reset(DemoConfig(enabled=False, reset_hours=2)) is None
