"""Memory chat recall at its default threshold, end to end with the real embedder and Qdrant
(in-memory): the sample incident history is imported, then asked about the way people ask (QA-16)."""

from __future__ import annotations

from pathlib import Path

import pytest
import qdrant_client
from fastapi.testclient import TestClient

from backend.app.main import create_app

_RealQdrantClient = qdrant_client.QdrantClient


def _in_memory_qdrant(*_args, **_kwargs) -> qdrant_client.QdrantClient:
    return _RealQdrantClient(":memory:")

INCIDENTS = Path(__file__).resolve().parents[2] / "sample_data" / "incident-import"

# Ordinary questions and the past incident each one is about. All of these scored 0.43-0.73 for the
# right case; 0.55, the old default, hid six of them.
QUESTIONS = [
    ("payments database connection storm", "Payments CPU spike from database connection storm"),
    ("payments pods reconnecting to the database at once", "Payments CPU spike from database connection storm"),
    ("runaway regex in coupon validator", "CPU usage above 90% on checkout"),
    ("disk filling up on metrics host", "Disk usage above 85% on metrics host"),
    ("cache stampede at midnight", "Search cache stampede at midnight"),
    ("search got slow at midnight", "Search cache stampede at midnight"),
    ("fraud scoring saturating payments cpu", "Payments CPU saturated by fraud scoring"),
    ("checkout GC pauses after memory limit change", "Checkout CPU and latency up from GC pauses"),
    ("what fixed checkout latency last time?", "Checkout CPU and latency up from GC pauses"),
]
OFF_TOPIC = ["what is the weather today", "how do I bake sourdough bread", "reset my password", "hello"]


@pytest.fixture(scope="module")
def client():
    # Module-scoped, so conftest's per-test _never_the_configured_qdrant isn't active yet: without
    # the same patch here the app reached for the Qdrant in config.yaml (localhost:6333, usually a
    # dev or demo stack) and imported these incidents into it.
    with pytest.MonkeyPatch.context() as patch:
        for module in ("backend.app.main", "backend.app.mcp_runtime", "backend.app.api.testing"):
            patch.setattr(f"{module}.QdrantClient", _in_memory_qdrant)
        patch.setattr(qdrant_client, "QdrantClient", _in_memory_qdrant)
        app = create_app("sqlite+pysqlite:///:memory:")
        with TestClient(app) as test_client:
            for name in ("pagerduty-incidents.csv", "postmortems.zip"):
                response = test_client.post("/api/case-imports", files={"files": (name, (INCIDENTS / name).read_bytes())})
                assert response.status_code == 200, response.text
                assert response.json()["indexed"] > 0, "embedding model unavailable"
            yield test_client


@pytest.mark.parametrize("path", ["/api/memory/chat", "/api/mcp/memory/chat"])
@pytest.mark.parametrize(("question", "incident"), QUESTIONS)
def test_the_right_past_incident_comes_back_at_the_default_threshold(client, path, question, incident) -> None:
    payload = client.post(path, json={"message": question}).json()

    assert payload["sources"], payload["answer"]
    assert payload["sources"][0]["title"] == incident


def test_a_possible_match_is_shown_and_called_one(client) -> None:
    payload = client.post("/api/memory/chat", json={"message": "cache stampede at midnight"}).json()

    top = payload["sources"][0]
    assert top["similarity_score"] < 0.70
    assert top["strength"] == "possible"
    assert "a possible match" in payload["answer"]
    assert "check that it fits" in payload["answer"]


def test_a_strong_match_is_not_hedged(client) -> None:
    payload = client.post("/api/memory/chat", json={"message": "runaway regex in coupon validator"}).json()

    assert payload["sources"][0]["strength"] == "strong"
    assert "possible match" not in payload["answer"]


@pytest.mark.parametrize("question", OFF_TOPIC)
def test_an_off_topic_question_finds_nothing(client, question) -> None:
    payload = client.post("/api/memory/chat", json={"message": question}).json()

    assert payload["sources"] == []
    assert payload["answer"].startswith("I could not find a related case")


def test_an_explicit_threshold_is_still_respected(client) -> None:
    payload = client.post("/api/memory/chat", json={"message": "cache stampede at midnight", "minimum_score": 0.55}).json()

    assert payload["sources"] == []
