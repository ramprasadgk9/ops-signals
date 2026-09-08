from __future__ import annotations

import time
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


@contextmanager
def state_isolation() -> Generator[dict[str, Any], None, None]:
    """Provides a fresh, isolated execution context per run.
    
    Guarantees no state leakage, no shared memory across repeated trials,
    and clean teardown.
    """
    context: dict[str, Any] = {
        "isolated": True,
        "started_at": time.perf_counter(),
    }
    try:
        yield context
    finally:
        context["completed_at"] = time.perf_counter()


class BaseBenchmarkRunner(ABC):
    """Abstract interface defining the dual input paradigms:
    1. Direct batch ingestion (used by IAM SignalPipeline)
    2. Interactive tool queries (used by ReAct agents like Baseline A)
    """

    def __init__(self, runner_id: str) -> None:
        self.runner_id = runner_id

    @abstractmethod
    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Executes telemetry triage via direct batch ingestion (IAM paradigm)."""
        pass

    @abstractmethod
    def get_query_environment(self, scenario_dir: Path) -> Any:
        """Returns interactive mock tools for agentic queries (Baseline A paradigm)."""
        pass
