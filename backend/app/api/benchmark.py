from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.benchmark.service import BenchmarkService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])
_benchmark_service = BenchmarkService()


class BenchmarkRunRequest(BaseModel):
    scenarios: list[str] | None = Field(
        default=None,
        description="List of scenario IDs to run (e.g. ['scenario_01_resource_degradation']). Runs all if omitted.",
    )
    provider: str = Field(
        default="mock",
        description="Provider for baseline and judge execution: 'mock', 'gemini', 'openai', or 'openrouter'.",
    )
    model_id: str | None = Field(
        default=None,
        description="Frontier model ID (e.g. 'gemini-3.8-flash', 'gemini-3.5-flash', 'gpt-4o').",
    )
    judge_provider: str | None = Field(
        default=None,
        description="Optional provider for judge evaluator. Defaults to runner provider or 'mock'.",
    )


@router.get("/scenarios")
def get_benchmark_scenarios() -> list[dict[str, Any]]:
    """Lists all available benchmark scenarios and their ground truth metadata."""
    try:
        return _benchmark_service.list_scenarios()
    except Exception as exc:
        logger.exception("Failed to list benchmark scenarios")
        raise HTTPException(status_code=500, detail=f"Failed to list benchmark scenarios: {exc}") from exc


@router.get("/report")
def get_benchmark_report() -> dict[str, Any]:
    """Retrieves the latest IAM vs. LLM benchmark evaluation report and Pareto summary."""
    try:
        return _benchmark_service.get_latest_report()
    except Exception as exc:
        logger.exception("Failed to retrieve benchmark report")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve benchmark report: {exc}") from exc


@router.post("/run")
def run_benchmark(request: BenchmarkRunRequest) -> dict[str, Any]:
    """Triggers an on-demand benchmark evaluation across scenarios and returns the updated report."""
    try:
        return _benchmark_service.run_benchmark(
            scenario_ids=request.scenarios,
            provider=request.provider,
            model_id=request.model_id,
            judge_provider=request.judge_provider,
        )
    except ValueError as exc:
        logger.warning("Benchmark validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Benchmark run execution failed")
        raise HTTPException(status_code=500, detail=f"Benchmark run execution failed: {exc}") from exc
