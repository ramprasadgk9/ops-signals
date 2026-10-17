"""QA-18: two people opening a case for the same finding at once. With sql/init.sql's unique index
one of them got a 500 (UniqueViolation); on a database the backend built itself (Helm, SQLite)
there was no index, so they got two cases."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.app.models.entities import Base, OperationalCaseEntity
from backend.app.models.schema_compat import ensure_case_link_unique_schema
from tests.api_backend.test_cases import _create_finding


def _miss_the_first_existing_case_check():
    """Lets a request pass the "case already exists?" check as if the other one hadn't committed yet."""
    real_execute = Session.execute
    state = {"missed": False}

    def execute(self, statement, *args, **kwargs):
        descriptions = getattr(statement, "column_descriptions", None) or []
        if not state["missed"] and descriptions and descriptions[0].get("entity") is OperationalCaseEntity:
            state["missed"] = True
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return real_execute(self, statement, *args, **kwargs)

    return patch.object(Session, "execute", execute)


def test_the_second_of_two_concurrent_creates_gets_the_first_case(client, db_session) -> None:
    finding_id = _create_finding()
    first = client.post(f"/api/cases/findings/{finding_id}/create")

    with _miss_the_first_existing_case_check():
        second = client.post(f"/api/cases/findings/{finding_id}/create")

    assert second.status_code == 200
    assert second.json()["case_id"] == first.json()["case_id"]
    assert db_session.scalar(
        select(func.count()).select_from(OperationalCaseEntity).where(OperationalCaseEntity.finding_id == finding_id)
    ) == 1


def test_upgrading_adds_the_indexes_but_leaves_existing_duplicates_alone(tmp_path, caplog) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX idx_ops_case_finding"))
        connection.execute(text("DROP INDEX idx_ops_case_behavior_finding"))
        for case_id in (1, 2):
            connection.execute(
                text(
                    "INSERT INTO ops_operational_cases (id, finding_id, analysis_run_id, case_title, case_status, finding_snapshot, "
                    "investigation_status, investigation_notes, root_cause_status, root_cause_verified, outcome_status, memory_status, "
                    "memory_opted_out, source, created_at, updated_at) VALUES (:id, 7, 'run', 't', 'open', '{}', 'not_started', '[]', "
                    "'unknown', 0, 'pending', 'not_indexed', 0, 'detected', '2026-10-01', '2026-10-01')"
                ),
                {"id": case_id},
            )

    with caplog.at_level(logging.WARNING):
        ensure_case_link_unique_schema(engine)
        ensure_case_link_unique_schema(engine)

    with engine.begin() as connection:
        indexes = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'")).scalars())
        assert connection.execute(text("SELECT COUNT(*) FROM ops_operational_cases")).scalar() == 2
    assert "idx_ops_case_behavior_finding" in indexes
    assert "idx_ops_case_finding" not in indexes
    assert "several cases share finding_id 7" in caplog.text
