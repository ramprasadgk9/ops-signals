"""Each finding says where its data came from (Prometheus, OTLP or CSV), and the findings list
filters by it, so a card can explain why one finding has a pod breakdown and another doesn't."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def api() -> TestClient:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        with get_session_local()() as db:
            for run_id, source_type in (("run-prom", "prometheus"), ("run-otel", "otel"), ("run-csv", "csv")):
                db.add(AnalysisRunEntity(
                    id=run_id, source_type=source_type, service="checkout-api", metric_name="error_rate",
                    start_time=NOW - timedelta(hours=1), end_time=NOW, sample_count=10, status="completed",
                ))
            # A finding whose run row is gone (or never existed) still lists, with no source.
            for run_id in ("run-prom", "run-otel", "run-csv", "run-missing"):
                db.add(FindingEntity(
                    analysis_run_id=run_id, service="checkout-api", metric_name="error_rate",
                    title=f"shift in {run_id}", summary="s", category="baseline_shift",
                    health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
                    created_at=NOW,
                ))
            db.commit()
        yield client


def _sources(response) -> dict[str, str | None]:
    assert response.status_code == 200, response.text
    return {finding["analysis_run_id"]: finding["source"] for finding in response.json()}


def test_findings_name_their_source_with_otel_runs_shown_as_otlp(api: TestClient) -> None:
    assert _sources(api.get("/api/findings")) == {
        "run-prom": "prometheus",
        "run-otel": "otlp",
        "run-csv": "csv",
        "run-missing": None,
    }


def test_a_single_finding_names_its_source(api: TestClient) -> None:
    finding_id = next(f["id"] for f in api.get("/api/findings").json() if f["analysis_run_id"] == "run-otel")
    assert api.get(f"/api/findings/{finding_id}").json()["source"] == "otlp"


@pytest.mark.parametrize("path", ["/api/findings", "/api/findings/search"])
@pytest.mark.parametrize("source, expected", [("prometheus", {"run-prom"}), ("otlp", {"run-otel"}), ("csv", {"run-csv"})])
def test_list_and_search_filter_by_source(api: TestClient, path: str, source: str, expected: set[str]) -> None:
    assert set(_sources(api.get(path, params={"source": source}))) == expected


@pytest.mark.parametrize("path", ["/api/findings", "/api/findings/search"])
def test_no_source_filter_returns_everything_as_before(api: TestClient, path: str) -> None:
    assert len(api.get(path).json()) == 4


def test_an_unknown_source_is_rejected(api: TestClient) -> None:
    assert api.get("/api/findings", params={"source": "kafka"}).status_code == 422
