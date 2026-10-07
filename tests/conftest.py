from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# create_app() starts backend.app.autonomous.scheduler.run_scheduler_loop() as a background
# asyncio task on every call. It offloads each tick to a thread pool (asyncio.to_thread) and
# re-resolves get_session_local() - a process-global - at execution time, not at task-creation
# time. Task cancellation on TestClient shutdown does not stop an in-flight thread (Python's
# documented asyncio.to_thread behavior), so a slow tick from one test's app can still be running
# when the next test calls create_app() and repoints the global session factory at a new
# in-memory DB - the stale tick then reads/writes into an unrelated test's database. Tests never
# exercise the background loop itself (test_autonomous_policies.py calls the tick function
# directly and synchronously), so disabling it here removes the race with no loss of coverage.
os.environ.setdefault("OPS_SIGNALS_AUTONOMOUS_SCHEDULER_ENABLED", "false")
os.environ.setdefault("OPS_SIGNALS_TICKETING_WORKER_ENABLED", "false")


import pytest  # noqa: E402
import qdrant_client  # noqa: E402

_RealQdrantClient = qdrant_client.QdrantClient


def _in_memory_qdrant(*_args, **_kwargs) -> qdrant_client.QdrantClient:
    return _RealQdrantClient(":memory:")


@pytest.fixture(autouse=True)
def _never_the_configured_qdrant(monkeypatch):
    """Every Qdrant client the app builds is in-memory. config.yaml points at localhost:6333,
    which is usually a running demo or dev stack: startup there runs the collection migration and
    the vector backfill against that stack's data, and indexing writes test cases into it.
    Tests that want a Qdrant create their own QdrantClient(":memory:")."""
    for module in ("backend.app.main", "backend.app.mcp_runtime", "backend.app.api.testing"):
        monkeypatch.setattr(f"{module}.QdrantClient", _in_memory_qdrant)
    # backend.app.case_import.cli imports it inside a function.
    monkeypatch.setattr(qdrant_client, "QdrantClient", _in_memory_qdrant)


@pytest.fixture(autouse=True, scope="session")
def _embed_each_text_once():
    """Every app startup indexes the assistant's documentation into its fresh in-memory Qdrant,
    which re-embeds about 870 chunks per test that builds the app (~4s, over 35 minutes on CI).
    MiniLM is deterministic, so each distinct text is embedded once per session and reused;
    every test still gets its own empty Qdrant."""
    from backend.app.memory.embedder import CaseEmbedder

    # Separate caches: a batch pads its texts together, so its vectors can differ from encode()'s
    # in the last float digits, and each path should return exactly what the model gives it.
    batch_cache: dict[str, tuple[float, ...]] = {}
    single_cache: dict[str, tuple[float, ...]] = {}
    real_encode_batch = CaseEmbedder.encode_batch
    real_encode = CaseEmbedder.encode

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in batch_cache))
        if missing:
            for text, vector in zip(missing, real_encode_batch(self, missing)):
                batch_cache[text] = tuple(vector)
        return [list(batch_cache[text]) for text in texts]

    def encode(self, text: str) -> list[float]:
        if text not in single_cache:
            single_cache[text] = tuple(real_encode(self, text))
        return list(single_cache[text])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CaseEmbedder, "encode_batch", encode_batch)
        patch.setattr(CaseEmbedder, "encode", encode)
        yield
