from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.app.benchmark.service import BenchmarkService
from backend.app.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app("sqlite+pysqlite:///:memory:")
    return TestClient(app)


def test_get_benchmark_scenarios(client: TestClient) -> None:
    response = client.get("/api/benchmark/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    scenario_ids = [s["id"] for s in data]
    assert "scenario_01_resource_degradation" in scenario_ids
    assert "scenario_02_cascading_failure" in scenario_ids
    assert "scenario_03_benign_maintenance" in scenario_ids

    scen_1 = next(s for s in data if s["id"] == "scenario_01_resource_degradation")
    assert scen_1["entity"] == "payment-service"
    assert scen_1["root_cause"] == "MEMORY_LEAK"
    assert scen_1["has_metrics"] is True


def test_get_benchmark_report(client: TestClient) -> None:
    response = client.get("/api/benchmark/report")
    assert response.status_code == 200
    data = response.json()
    assert "scenarios" in data
    assert "summary" in data
    assert "generated_at" in data

    summary = data["summary"]
    assert "iam" in summary
    assert "baseline_a" in summary
    assert "baseline_b" in summary
    assert "pareto" in summary

    iam_summary = summary["iam"]
    assert iam_summary["total_tokens"] == 0
    assert iam_summary["total_cost_usd"] == 0.0

    pareto = summary["pareto"]
    assert pareto["iam_cost_per_incident"] == "$0.00"
    assert pareto["token_reduction_vs_a_pct"] >= 95.0


def test_run_benchmark_validation_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Unsupported provider
    res_invalid = client.post(
        "/api/benchmark/run",
        json={"provider": "unsupported_provider"},
    )
    assert res_invalid.status_code == 400
    assert "Unsupported provider" in res_invalid.json()["detail"]

    # 2. Missing Gemini API key
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BENCHMARK_LLM_API_KEY", raising=False)
    res_gemini_missing_key = client.post(
        "/api/benchmark/run",
        json={"provider": "gemini"},
    )
    assert res_gemini_missing_key.status_code == 400
    assert "GEMINI_API_KEY is not configured" in res_gemini_missing_key.json()["detail"]


def test_run_benchmark_mock_execution(client: TestClient) -> None:
    res = client.post(
        "/api/benchmark/run",
        json={
            "scenarios": ["scenario_01_resource_degradation"],
            "provider": "mock",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "scenarios" in data
    assert "summary" in data
    assert len(data["scenarios"]) >= 1
