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

    # 2. Missing Gemini API key for runner
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BENCHMARK_LLM_API_KEY", raising=False)
    res_gemini_missing_key = client.post(
        "/api/benchmark/run",
        json={"provider": "gemini"},
    )
    assert res_gemini_missing_key.status_code == 400
    assert "GEMINI_API_KEY" in res_gemini_missing_key.json()["detail"]

    # 3. Missing Gemini API key for judge_provider
    res_judge_missing_key = client.post(
        "/api/benchmark/run",
        json={"provider": "mock", "judge_provider": "gemini"},
    )
    assert res_judge_missing_key.status_code == 400
    assert "GEMINI_API_KEY" in res_judge_missing_key.json()["detail"]


def test_run_benchmark_mock_execution(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.api import benchmark as benchmark_api_module

    temp_report = tmp_path / "benchmark_report.json"
    monkeypatch.setattr(benchmark_api_module._benchmark_service, "report_file", temp_report)

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


def test_run_benchmark_partial_run_preserves_other_scenarios(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from backend.app.api import benchmark as benchmark_api_module

    # Pre-populate isolated report with scenario_01
    temp_report = tmp_path / "benchmark_report.json"
    initial_data = [
        {
            "scenario": "scenario_01_resource_degradation",
            "ground_truth": {"entity": "payment-service", "root_cause": "MEMORY_LEAK"},
            "iam": {"runner_id": "iam_advisor", "status": "SUCCESS"},
        }
    ]
    temp_report.write_text(json.dumps(initial_data), encoding="utf-8")
    monkeypatch.setattr(benchmark_api_module._benchmark_service, "report_file", temp_report)

    # Trigger run for only scenario_02
    res_partial = client.post(
        "/api/benchmark/run",
        json={
            "scenarios": ["scenario_02_cascading_failure"],
            "provider": "mock",
        },
    )
    assert res_partial.status_code == 200
    data = res_partial.json()

    # Deterministic assertion: scenario_01 must be preserved and scenario_02 added
    scen_ids = [s["scenario"] for s in data["scenarios"]]
    assert "scenario_01_resource_degradation" in scen_ids
    assert "scenario_02_cascading_failure" in scen_ids
    assert len(data["scenarios"]) == 2


def test_get_benchmark_report_empty_or_corrupt_file_handling(tmp_path: Path) -> None:
    from backend.app.benchmark.service import BenchmarkService

    # 1. Non-existent report file
    service_missing = BenchmarkService(repo_root=tmp_path / "missing_case")
    res_missing = service_missing.get_latest_report()
    assert res_missing["scenarios"] == []
    assert res_missing["generated_at"] is None
    assert not service_missing.report_file.exists()

    # 2. 0-byte report file
    service_empty = BenchmarkService(repo_root=tmp_path / "empty_case")
    service_empty.report_file.parent.mkdir(parents=True, exist_ok=True)
    service_empty.report_file.write_text("", encoding="utf-8")
    res_empty = service_empty.get_latest_report()
    assert res_empty["scenarios"] == []
    assert res_empty["generated_at"] is not None

    # 3. Corrupt JSON report file
    service_corrupt = BenchmarkService(repo_root=tmp_path / "corrupt_case")
    service_corrupt.report_file.parent.mkdir(parents=True, exist_ok=True)
    service_corrupt.report_file.write_text("{corrupt json", encoding="utf-8")
    res_corrupt = service_corrupt.get_latest_report()
    assert res_corrupt["scenarios"] == []
    assert res_corrupt["generated_at"] is not None
