from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.api import memory as memory_module
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, NormalizedPoint
from intelligence.analyzers.baseline_shift import BaselineShiftAnalyzer


def _cpu_dataframe(values: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, 0, 0, 0)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index * 5) for index in range(len(values))],
            "metric_name": ["cpu_usage"] * len(values),
            "value": values,
            "service": ["checkout-api"] * len(values),
            "env": ["prod"] * len(values),
        }
    )


def test_analyzer_scenario_detects_baseline_shift_from_sampled_cpu_data() -> None:
    values = [42.0, 42.5, 41.8, 42.2, 41.9, 78.0, 79.1, 78.4, 80.0, 79.5, 78.8, 79.2]
    analyzer = BaselineShiftAnalyzer(threshold_percent=25.0, min_segment_size=4, change_threshold=1.5)

    signals = analyzer.analyze(_cpu_dataframe(values))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == "baseline_shift"
    assert signal.metric_name == "cpu_usage"
    assert signal.service == "checkout-api"
    assert signal.evidence["library"] == "ruptures"
    assert signal.evidence["change_point_index"] > 0
    assert signal.evidence["percent_change"] > 25.0


def test_analyzer_scenario_keeps_stable_cpu_data_from_becoming_false_positive_finding() -> None:
    values = [50.0, 50.1, 49.9, 50.0, 50.2, 49.8, 50.1, 50.0, 49.9, 50.1, 50.0, 49.8]
    analyzer = BaselineShiftAnalyzer(threshold_percent=25.0, min_segment_size=4, change_threshold=1.5)

    signals = analyzer.analyze(_cpu_dataframe(values))

    assert signals == []


def test_cases_api_scenario_creates_case_from_finding_and_persists_case_snapshot() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    # This scenario is about case creation, not memory indexing - keep it independent of
    # whether a real Qdrant happens to be reachable in this environment.
    app.dependency_overrides[memory_module.get_memory_indexer] = lambda: None
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(
                FindingEntity(
                    id=101,
                    analysis_run_id="run-case-scenario",
                    service="checkout-api",
                    metric_name="cpu_usage",
                    title="CPU usage baseline shifted",
                    summary="CPU moved from normal baseline to sustained high usage.",
                    category="behavior_change",
                    health_status="critical",
                    importance_score=0.94,
                    investigation_priority=1,
                    signal_ids=["sig-101"],
                    comparison_json={"comparison_type": "selected_window_split"},
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()

        create_response = client.post("/api/cases/findings/101/create")
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["case_status"] == "open"
        assert created["memory_status"] == "not_indexed"

        case_response = client.get(f"/api/cases/{created['case_id']}")
        assert case_response.status_code == 200
        case_payload = case_response.json()
        assert case_payload["case_title"] == "CPU usage baseline shifted"
        assert case_payload["analysis_run_id"] == "run-case-scenario"
        assert case_payload["finding_snapshot"]["service"] == "checkout-api"
        assert case_payload["finding_snapshot"]["metric_name"] == "cpu_usage"


def test_recommendation_api_scenario_returns_grouped_analyzer_decisions_for_trending_metric() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            start = datetime.utcnow() - timedelta(hours=3)
            for index in range(72):
                db.add(
                    NormalizedPoint(
                        metric_name="memory_usage",
                        timestamp=start + timedelta(minutes=index * 2),
                        value=100 + index * 0.75,
                        service="checkout-api",
                        analysis_run_id="run-recommendation-scenario",
                    )
                )
            db.commit()

        response = client.post(
            "/api/metric-analyzer-recommendations/evaluate",
            json={
                "service": "checkout-api",
                "metric_name": "memory_usage",
                "analysis_run_id": "run-recommendation-scenario",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    recommendations = payload["recommendations"]
    groups = {item["recommendation"] for item in recommendations}
    assert payload["profile"]["sample_count"] == 72
    assert "recommended" in groups
    assert {"recommended", "conditional", "not_recommended"}.intersection(groups)
    # A straight upward line: the trend analyzer is the right pick. (This used to expect
    # statsforecast_forecast, the only analyzer that could win while the page's router profile
    # lacked detected_profiles and every behavior-restricted analyzer was rejected.)
    assert any(
        item["analyzer_id"] == "trend" and item["recommendation"] == "recommended"
        for item in recommendations
    )
