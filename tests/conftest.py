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
