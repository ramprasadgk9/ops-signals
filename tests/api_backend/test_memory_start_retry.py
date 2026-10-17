"""QA-10 (rest): with Qdrant unreachable at startup, operational memory stayed off until a restart.
/api/memory/health said "initializing" forever, and seen-before said memory was "not enabled"."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.api import memory as memory_module
from backend.app.config import MemoryConfig
from backend.app.main import create_app
from backend.app.memory import availability
from backend.app.memory.seen_before import find_seen_before

_NOTHING = (None, None, None, None, None, None)


def _qdrant_down_then_up():
    store = SimpleNamespace(health=lambda: {"status": "healthy"})
    indexer = SimpleNamespace(name="indexer")
    attempts = {"count": 0}

    def initialize(_config):
        attempts["count"] += 1
        if attempts["count"] == 1:
            availability.mark(availability.UNAVAILABLE)
            return _NOTHING
        return store, object(), indexer, object(), None, None

    return initialize, indexer, attempts


async def _no_catch_up(*_args, **_kwargs) -> None:
    return None


def test_memory_reports_unavailable_then_starts_once_qdrant_is_back() -> None:
    initialize, indexer, attempts = _qdrant_down_then_up()
    with (
        patch.object(main_module, "load_memory_config", lambda: MemoryConfig(enabled=True)),
        patch.object(main_module, "initialize_memory_services", initialize),
        patch.object(main_module, "run_memory_catch_up_loop", _no_catch_up),
        patch.object(main_module, "waiting_at_startup", lambda *_: False),
        patch.object(main_module, "_needs_backfill", lambda _indexer: False),
        patch.object(main_module, "MEMORY_RETRY_FIRST_SECONDS", 0.2),
    ):
        app = create_app("sqlite+pysqlite:///:memory:")
        with TestClient(app) as client:
            down = client.get("/api/memory/health").json()
            assert down["status"] == "unavailable"
            assert "can't reach its vector store" in down["detail"]
            assert client.get("/api/memory/stats").json()["status"] == "unavailable"

            deadline = time.monotonic() + 5
            while memory_module._services["indexer"] is not indexer and time.monotonic() < deadline:
                time.sleep(0.05)

            assert attempts["count"] == 2
            up = client.get("/api/memory/health").json()
            assert up["status"] == "healthy"
            assert up["detail"] is None
            assert availability.status() == availability.READY
    availability.mark(availability.DISABLED)


def test_memory_features_say_why_memory_is_off() -> None:
    finding = SimpleNamespace(id=1, service="checkout", metric_name="cpu_usage")
    try:
        availability.mark(availability.UNAVAILABLE)
        reason = find_seen_before(None, finding, None, None).reason
        assert reason.startswith("Operational memory can't reach its vector store right now, so past cases can't be searched")

        availability.mark(availability.DISABLED)
        assert find_seen_before(None, finding, None, None).reason == "Operational memory is not enabled, so past cases can't be searched."
    finally:
        availability.mark(availability.DISABLED)
