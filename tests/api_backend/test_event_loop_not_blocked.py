"""QA-04: endpoints that do blocking work must not run it on the event loop.

Each test makes one endpoint's blocking part take SLOW_SECONDS, fires it, and while it is in flight
calls /api/health. Run on the event loop (an `async def` handler calling blocking code), the health
check waited for the slow request to finish: 9.16 s behind a CSV upload whose Slack post hung.
Off the loop, it answers at once.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.api import memory as memory_api
from backend.app.config import MemoryConfig
from backend.app.main import create_app

# Shared CI runners answered /api/health in up to 1.24 s with nothing blocking, so CI gets a looser
# limit and a longer slow part: blocked, the health check waits at least SLOW_SECONDS - 0.3, which
# must stay well above the limit for the test to still catch a blocked event loop.
if os.environ.get("CI"):
    SLOW_SECONDS = 4.0
    HEALTH_LIMIT_SECONDS = 2.0
else:
    SLOW_SECONDS = 2.0
    HEALTH_LIMIT_SECONDS = 0.5


def _slow(result=None):
    def blocking(*_args, **_kwargs):
        time.sleep(SLOW_SECONDS)
        return result

    return blocking


def _csv_bytes() -> bytes:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = ["timestamp,metric_name,value"]
    rows.extend(f"{(start + timedelta(minutes=5 * index)).isoformat()},cpu_usage,{50 + index % 3}" for index in range(60))
    return "\n".join(rows).encode("utf-8")


async def _health_latency_during(app, send_slow_request) -> tuple[float, float]:
    """Seconds /api/health took while the slow request ran, and seconds the slow request took."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
        started = time.perf_counter()
        slow = asyncio.create_task(send_slow_request(client))
        # Timed from when the health check was due, not when it was sent: a blocked event loop also
        # holds up this sleep, so starting the clock after it would hide exactly the wait we test for.
        health_due = time.perf_counter() + 0.3
        await asyncio.sleep(0.3)
        health = await client.get("/api/health")
        health_seconds = time.perf_counter() - health_due
        # Only the timing matters: the mocked slow part returns a stand-in the endpoint may then
        # fail to serialize after the sleep.
        await asyncio.gather(slow, return_exceptions=True)
        slow_seconds = time.perf_counter() - started
    assert health.status_code == 200
    return health_seconds, slow_seconds


def _assert_not_blocked(health_seconds: float, slow_seconds: float) -> None:
    # The slow request really was slow, so the health check really ran while it was in flight.
    assert slow_seconds >= SLOW_SECONDS
    assert health_seconds < HEALTH_LIMIT_SECONDS, f"/api/health waited {health_seconds:.2f}s behind a blocking request"


@pytest.fixture()
def app():
    with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
        yield create_app("sqlite+pysqlite:///:memory:")


def test_a_slow_csv_run_does_not_block_other_requests(app) -> None:
    async def send(client):
        await client.post(
            "/api/ingestion/csv-run",
            data={"provider": "generic", "service": "checkout", "metric_name": "cpu_usage"},
            files={"file": ("cpu.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        )

    with patch("backend.app.api.ingestion.SignalPipeline") as pipeline_cls:
        pipeline_cls.return_value.run.side_effect = _slow()
        _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))


def test_a_slow_csv_validation_does_not_block_other_requests(app) -> None:
    async def send(client):
        await client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all"},
            files={"file": ("cpu.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        )

    with patch("backend.app.api.ingestion.SignalPipeline") as pipeline_cls:
        pipeline_cls.return_value.run.side_effect = _slow()
        _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))


def test_a_slow_prometheus_run_does_not_block_other_requests(app) -> None:
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    payload = {
        "provider": "prometheus",
        "datasource_uid": "prom",
        "service": "checkout",
        "metric_name": "cpu_usage",
        "promql": "cpu_usage",
        "from": now.isoformat(),
        "to": (now + timedelta(hours=1)).isoformat(),
        "step_seconds": 60,
        "series_count": 1,
        "sample_count": 1,
        "samples": [{"timestamp": now.isoformat(), "value": 1.0, "metric_name": "cpu_usage", "service": "checkout"}],
    }

    async def send(client):
        await client.post("/api/ingestion/prometheus-run", json=payload)

    with patch("backend.app.api.ingestion.SignalPipeline") as pipeline_cls:
        pipeline_cls.return_value.run_dataframe.side_effect = _slow()
        _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))


def test_a_slow_incident_import_does_not_block_other_requests(app) -> None:
    async def send(client):
        await client.post("/api/case-imports/preview", files=[("files", ("cases.csv", io.BytesIO(b"id,title\n1,a\n"), "text/csv"))])

    with patch("backend.app.api.case_imports.parse_files", side_effect=_slow(MagicMock())), patch(
        "backend.app.api.case_imports.CaseImportService"
    ):
        _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))


def test_a_slow_memory_chat_does_not_block_other_requests(app) -> None:
    embedder = MagicMock()
    embedder.encode.side_effect = _slow([0.0] * 384)
    service = MagicMock()
    service.vector_store.search.return_value = []
    app.dependency_overrides[memory_api.get_memory_config] = lambda: MemoryConfig(enabled=True)
    app.dependency_overrides[memory_api.get_similarity_service] = lambda: service
    app.dependency_overrides[memory_api.get_embedder] = lambda: embedder

    async def send(client):
        await client.post("/api/memory/chat", json={"message": "why is checkout slow"})

    _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))
    embedder.encode.assert_called_once()


def test_a_slow_otlp_export_does_not_block_other_requests(app) -> None:
    body = b'{"resourceMetrics": []}'

    async def send(client):
        await client.post("/api/otlp/v1/metrics", content=body, headers={"content-type": "application/json"})

    with patch("backend.app.api.otlp.convert_export_request", side_effect=_slow(MagicMock(points=[], rejected_unsupported_type=0, rejected_missing_value=0))):
        _assert_not_blocked(*asyncio.run(_health_latency_during(app, send)))


def test_csv_runs_started_together_still_run_one_at_a_time(app) -> None:
    # Off the event loop, uploads would really run in parallel; their catalog writes then collided
    # (duplicate keys, deadlocks on Postgres). They take turns, as before, in worker threads.
    running = 0
    most_at_once = 0
    lock = threading.Lock()

    def run(*_args, **_kwargs):
        nonlocal running, most_at_once
        with lock:
            running += 1
            most_at_once = max(most_at_once, running)
        time.sleep(0.3)
        with lock:
            running -= 1

    async def send_four(client):
        await asyncio.gather(
            *(
                client.post(
                    "/api/ingestion/csv-run",
                    data={"provider": "generic", "service": f"svc-{index}", "metric_name": "cpu_usage"},
                    files={"file": ("cpu.csv", io.BytesIO(_csv_bytes()), "text/csv")},
                )
                for index in range(4)
            ),
            return_exceptions=True,
        )

    with patch("backend.app.api.ingestion.SignalPipeline") as pipeline_cls:
        pipeline_cls.return_value.run.side_effect = run
        health_seconds, _ = asyncio.run(_health_latency_during(app, send_four))

    assert most_at_once == 1
    assert health_seconds < HEALTH_LIMIT_SECONDS
