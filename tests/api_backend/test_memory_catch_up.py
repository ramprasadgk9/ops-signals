"""QA-11: a case created while Qdrant was down stayed `not_indexed` after recovery and restart,
missing from similar-case search, while memory stats said "healthy"."""

from __future__ import annotations

from unittest.mock import patch

from backend.app.config import IndexingConfig, MemoryConfig, VectorStoreConfig
from backend.app.memory.catch_up import catch_up_case_memory, count_waiting
from backend.app.memory.qdrant_initializer import QdrantInitializer
from tests.api_backend.test_memory_recall import _add_case, embedder, memory  # noqa: F401


def _config(**indexing) -> MemoryConfig:
    return MemoryConfig(
        enabled=True,
        vector_store=VectorStoreConfig(collection_name=QdrantInitializer.COLLECTION_NAME),
        indexing=IndexingConfig(**indexing),
    )


def test_cases_an_outage_kept_out_of_memory_are_indexed(db_session, memory) -> None:
    missed = _add_case(db_session, "db_pool")
    failed = _add_case(db_session, "auth_cert")
    failed.memory_status = "failed"
    db_session.commit()

    assert count_waiting(db_session, _config()) == 2
    assert catch_up_case_memory(db_session, memory.indexer, _config()) == 2

    assert {missed.memory_status, failed.memory_status} == {"indexed"}
    assert count_waiting(db_session, _config()) == 0
    assert memory.client.count(QdrantInitializer.COLLECTION_NAME).count == 2


def test_a_case_the_user_removed_from_memory_stays_out(db_session, memory) -> None:
    case = _add_case(db_session, "db_pool")
    memory.indexer.index_case(case, db_session)
    memory.indexer.delete_memory(case, db_session)

    assert catch_up_case_memory(db_session, memory.indexer, _config()) == 0
    assert (case.memory_status, case.memory_opted_out) == ("not_indexed", True)

    # Adding it back by hand clears the opt-out.
    memory.indexer.index_case(case, db_session)
    assert case.memory_opted_out is False


def test_stale_cases_are_refreshed_only_with_automatic_updates_on(db_session, memory) -> None:
    case = _add_case(db_session, "db_pool")
    memory.indexer.index_case(case, db_session)
    case.memory_status = "stale"
    db_session.commit()

    assert catch_up_case_memory(db_session, memory.indexer, _config(automatic_on_case_update=False)) == 0
    assert catch_up_case_memory(db_session, memory.indexer, _config()) == 1
    assert case.memory_status == "indexed"


def test_nothing_is_added_when_automatic_indexing_is_off(db_session, memory) -> None:
    case = _add_case(db_session, "db_pool")
    config = _config(automatic_on_case_creation=False, automatic_on_case_update=False)

    assert count_waiting(db_session, config) == 0
    assert catch_up_case_memory(db_session, memory.indexer, config) == 0
    assert case.memory_status == "not_indexed"


def test_a_case_stuck_indexing_is_retried_only_at_startup(db_session, memory) -> None:
    case = _add_case(db_session, "db_pool")
    case.memory_status = "indexing"
    db_session.commit()

    assert catch_up_case_memory(db_session, memory.indexer, _config()) == 0
    assert catch_up_case_memory(db_session, memory.indexer, _config(), at_startup=True) == 1
    assert case.memory_status == "indexed"


def test_with_qdrant_still_down_it_stops_and_tries_again_later(db_session, memory) -> None:
    first = _add_case(db_session, "db_pool")
    second = _add_case(db_session, "auth_cert")

    with patch.object(memory.indexer.vector_store, "upsert", side_effect=ConnectionError("qdrant unreachable")):
        assert catch_up_case_memory(db_session, memory.indexer, _config()) == 0
    assert first.memory_status == "failed"
    assert second.memory_status == "not_indexed"

    assert catch_up_case_memory(db_session, memory.indexer, _config()) == 2


def test_memory_stats_count_failed_cases_and_what_is_waiting(client, db_session) -> None:
    failed = _add_case(db_session, "db_pool")
    failed.memory_status = "failed"
    _add_case(db_session, "auth_cert")
    db_session.commit()

    with patch("backend.app.api.memory._services", {"config": _config(), "vector_store": None}):
        stats = client.get("/api/memory/stats").json()

    assert stats["error_cases"] == 1
    assert stats["waiting_to_index"] == 2


def test_upgrading_keeps_cases_that_were_not_indexed_out_of_catch_up(tmp_path) -> None:
    # Old databases can't tell a case the user removed from one an outage kept out, so existing
    # not_indexed cases are treated as removed; failed ones are still caught up.
    from sqlalchemy import create_engine, text

    from backend.app.models.entities import Base
    from backend.app.models.schema_compat import ensure_case_memory_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ops_operational_cases DROP COLUMN memory_opted_out"))
        for case_id, status in ((1, "not_indexed"), (2, "failed"), (3, "indexed")):
            connection.execute(
                text(
                    "INSERT INTO ops_operational_cases (id, analysis_run_id, case_title, case_status, finding_snapshot, "
                    "investigation_status, investigation_notes, root_cause_status, root_cause_verified, outcome_status, memory_status, source, source_id, created_at, updated_at) "
                    "VALUES (:id, 'run', 't', 'open', '{}', 'not_started', '[]', 'unknown', 0, 'pending', :status, 'jira', :id, '2026-10-01', '2026-10-01')"
                ),
                {"id": case_id, "status": status},
            )

    ensure_case_memory_schema(engine)
    ensure_case_memory_schema(engine)

    with engine.begin() as connection:
        opted_out = dict(connection.execute(text("SELECT id, memory_opted_out FROM ops_operational_cases")).all())
    assert opted_out == {1: 1, 2: 0, 3: 0}
