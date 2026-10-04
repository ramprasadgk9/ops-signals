from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity
from backend.app.models.schema_compat import ensure_cluster_schema


def _finding(cluster: str | None, title: str) -> FindingEntity:
    return FindingEntity(
        service="checkout",
        metric_name="http_requests",
        cluster=cluster,
        title=title,
        summary="spike",
        category="unusual_activity",
        health_status="significant",
        importance_score=0.7,
        investigation_priority=2,
        signal_ids=[],
        comparison_json={},
        created_at=datetime.now(timezone.utc),
    )


def test_findings_api_returns_and_filters_by_cluster() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        with get_session_local()() as db:
            db.add_all([_finding("eu", "eu spike"), _finding("us", "us spike"), _finding(None, "single cluster")])
            db.commit()
        everything = client.get("/api/findings").json()
        only_us = client.get("/api/findings?cluster=us").json()

    assert sorted(item["cluster"] or "" for item in everything) == ["", "eu", "us"]
    assert [item["title"] for item in only_us] == ["us spike"]


def test_cluster_columns_are_added_to_an_existing_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ops_normalized_timeseries_points (id INTEGER PRIMARY KEY, metric_name TEXT)"))
        connection.execute(text("CREATE TABLE ops_operational_signals (id INTEGER PRIMARY KEY, metric_name TEXT)"))
        connection.execute(text("CREATE TABLE ops_operational_findings (id INTEGER PRIMARY KEY, metric_name TEXT)"))

    ensure_cluster_schema(engine)
    ensure_cluster_schema(engine)

    inspector = inspect(engine)
    for table in ("ops_normalized_timeseries_points", "ops_operational_signals", "ops_operational_findings"):
        assert "cluster" in {column["name"] for column in inspector.get_columns(table)}
