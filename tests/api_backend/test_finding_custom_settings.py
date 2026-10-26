"""Findings made with per-service analyzer settings say so, and don't claim the tested numbers,
which were measured with the default settings."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, SignalEntity

TREND_SETTING = {
    "analyzer_id": "trend",
    "analyzer": "Trend Analysis",
    "path": "finding_rules.min_slope_percent",
    "label": "Smallest steady climb or drop that counts, as % of the metric's usual level",
    "value": 5,
    "default": 10,
}
OVERRIDE = {"id": "payments_memory", "file": "payments-team.yml", "reason": "Memory grows slowly here."}


def _seed(executed: list[dict] | None) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add(AnalysisRunEntity(id="run-1", source_type="prometheus", service="payments-api", metric_name="memory",
                                 start_time=now, end_time=now, sample_count=10, status="completed", executed_analyzers_json=executed))
        for finding_id, service, analyzer, signal_type in (
            (1, "payments-api", "trend", "trend"),
            # Same run, another analyzer: the override didn't touch it.
            (2, "payments-api", "ruptures", "ruptures"),
            # Another service in the same (CSV) run, on the default settings.
            (3, "checkout-api", "trend", "trend"),
        ):
            db.add(SignalEntity(signal_id=f"sig-{finding_id}", signal_type=signal_type, analyzer_id=analyzer, metric_name="memory", service=service,
                                severity="high", start_time=now, end_time=now, evidence_json={}, importance_score=0.7, analysis_run_id="run-1"))
            db.add(FindingEntity(id=finding_id, analysis_run_id="run-1", service=service, metric_name="memory", title=f"finding {finding_id}",
                                 summary="s", category="behavior_change", health_status="significant", importance_score=0.7,
                                 investigation_priority=2, signal_ids=[f"sig-{finding_id}"], comparison_json={}, created_at=now))
        db.commit()


def _trend_snapshot() -> dict:
    return {
        "router_analyzer_id": "trend_regression",
        "pipeline_analyzer_ids": ["trend"],
        "execution_status": "completed",
        "settings_overrides": [
            {
                "series": [{"service": "payments-api", "metric": "memory"}],
                "applied": ["payments_memory"],
                "params": {"trend": {"finding_rules": {"min_slope_percent": 5}}},
                "disabled": [],
                "overrides": [OVERRIDE],
                "settings": [TREND_SETTING],
            }
        ],
    }


def test_a_finding_from_a_tuned_analyzer_carries_its_settings_and_no_tested_numbers(client: TestClient) -> None:
    _seed([_trend_snapshot(), {"router_analyzer_id": "ruptures", "pipeline_analyzer_ids": ["ruptures"], "execution_status": "completed"}])

    by_id = {item["id"]: item for item in client.get("/api/findings").json()}

    tuned = by_id[1]
    assert tuned["custom_settings"] == {"settings": [TREND_SETTING], "overrides": [OVERRIDE]}
    assert tuned["trust"]["tested"] is None
    assert tuned["trust"]["custom_settings"] is True
    # The analyzer behind it wasn't changed, or the series isn't the one the override was for.
    for untouched in (by_id[2], by_id[3]):
        assert untouched["custom_settings"] is None
        assert "custom_settings" not in untouched["trust"]

    assert client.get("/api/findings/1").json()["custom_settings"] == tuned["custom_settings"]


def test_findings_from_runs_without_overrides_are_unchanged(client: TestClient) -> None:
    _seed([{"router_analyzer_id": "trend_regression", "pipeline_analyzer_ids": ["trend"], "execution_status": "completed"}])

    for item in client.get("/api/findings").json():
        assert item["custom_settings"] is None
        assert "custom_settings" not in item["trust"]
