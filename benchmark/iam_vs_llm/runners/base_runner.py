from __future__ import annotations

import gc
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass


@dataclass(slots=True)
class BenchmarkRunResult:
    """Standardized output produced by any benchmark runner (IAM or Baseline)."""
    runner_id: str
    scenario_id: str
    normalized_rca: NormalizedRCA
    execution_time_seconds: float
    token_usage: int = 0
    cost_usd: float = 0.0
    tool_iterations: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IsolationContext:
    run_id: str
    temp_dir: Path
    started_at: float
    cleanup_callbacks: list[Any] = field(default_factory=list)

    def register_cleanup(self, callback: Any) -> None:
        self.cleanup_callbacks.append(callback)


@contextmanager
def state_isolation() -> Generator[IsolationContext, None, None]:
    """Provides a fresh, isolated execution context per run.
    
    Guarantees no state leakage, creates an ephemeral temp directory,
    resets backend DB singletons, and enforces clean teardown.
    """
    import backend.app.models.db as db_module

    # Reset any cached SQLAlchemy singletons
    prev_engine = db_module._engine
    prev_session = db_module._SessionLocal
    db_module._engine = None
    db_module._SessionLocal = None

    with tempfile.TemporaryDirectory(prefix="iam_bench_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        ctx = IsolationContext(
            run_id=uuid.uuid4().hex,
            temp_dir=temp_dir,
            started_at=time.perf_counter(),
        )
        try:
            yield ctx
        finally:
            for cb in ctx.cleanup_callbacks:
                try:
                    cb()
                except Exception:
                    pass

            # Restore or cleanly terminate engine
            if db_module._engine is not None:
                try:
                    db_module._engine.dispose()
                except Exception:
                    pass
            db_module._engine = prev_engine
            db_module._SessionLocal = prev_session
            gc.collect()


class BaseBenchmarkRunner(ABC):
    """Abstract interface defining the dual input paradigms:
    1. Direct batch ingestion (used by IAM SignalPipeline)
    2. Interactive tool queries (used by ReAct agents like Baseline A)
    """

    def __init__(self, runner_id: str) -> None:
        self.runner_id = runner_id

    @abstractmethod
    def execute(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Polymorphic entrypoint to execute benchmark evaluation for the scenario."""
        pass

    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Executes telemetry triage via batch ingestion. Defaults to execute()."""
        return self.execute(scenario_dir)

    def get_query_environment(self, scenario_dir: Path) -> Any | None:
        """Returns interactive mock tools for agentic queries if supported, else None."""
        return None
