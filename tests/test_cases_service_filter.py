from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.cases import router as cases_router
from backend.app.models.db import get_db
from backend.app.models.entities import Base, BehaviorFindingEntity, FindingEntity, OperationalCaseEntity

NOW = datetime(2026, 10, 25, 12, 0, 0)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[FindingEntity.__table__, BehaviorFindingEntity.__table__, OperationalCaseEntity.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(cases_router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _case(service: str, metric: str, hours_ago: int) -> OperationalCaseEntity:
    # Imported cases need no finding row to link to; the filter treats both kinds the same.
    when = NOW - timedelta(hours=hours_ago)
    return OperationalCaseEntity(
        source="csv",
        source_id=f"{service}-{metric}-{hours_ago}",
        analysis_run_id="run-1",
        case_title=f"{service} {metric}",
        finding_snapshot={"service": service, "metric_name": metric},
        created_at=when,
        updated_at=when,
    )


def test_service_filter_applies_before_the_limit(db: Session) -> None:
    # Five newer checkout cases, then one older payments case.
    db.add_all([_case("checkout-api", "errors", hours) for hours in range(1, 6)] + [_case("payments-api", "latency", 24)])
    db.commit()

    response = _client(db).get("/api/cases", params={"service": "payments-api", "limit": 3})

    assert response.status_code == 200
    assert [item["finding_snapshot"]["service"] for item in response.json()] == ["payments-api"]


def test_service_and_metric_filters_combine_and_keep_newest_first(db: Session) -> None:
    db.add_all([
        _case("payments-api", "latency", 5),
        _case("payments-api", "errors", 3),
        _case("payments-api", "latency", 1),
        _case("checkout-api", "latency", 2),
    ])
    db.commit()
    client = _client(db)

    latency = client.get("/api/cases", params={"service": "payments-api", "metric_name": "latency"}).json()
    assert [item["case_title"] for item in latency] == ["payments-api latency", "payments-api latency"]
    assert latency[0]["updated_at"] > latency[1]["updated_at"]
    assert len(client.get("/api/cases", params={"service": "payments-api"}).json()) == 3
    assert len(client.get("/api/cases").json()) == 4
    assert client.get("/api/cases", params={"service": "billing-worker"}).json() == []


def test_postgres_query_filters_on_the_snapshot_text() -> None:
    query = select(OperationalCaseEntity).where(OperationalCaseEntity.finding_snapshot["service"].as_string() == "payments-api")
    assert "finding_snapshot ->> " in str(query.compile(dialect=postgresql.dialect()))
