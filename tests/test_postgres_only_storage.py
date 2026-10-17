"""QA-28: concurrent analysis runs rewriting the capability catalog on Postgres failed with
duplicate keys or deadlocks. Needs a real Postgres (SQLite has one writer at a time), so it runs
only when OPS_SIGNALS_TEST_DATABASE_URL points at a disposable database."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from intelligence.storage.postgres_store import PostgresStore

DATABASE_URL = os.getenv("OPS_SIGNALS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set OPS_SIGNALS_TEST_DATABASE_URL to a disposable Postgres")

CAPABILITIES = [
    {"id": f"capability_{index}", "analyzer_id": f"analyzer_{index}", "title": "t", "description": "d", "supported_question_ids": ["q1", "q2"]}
    for index in range(12)
]


def test_concurrent_runs_rewrite_the_catalog_without_failing() -> None:
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with patch.object(PostgresStore, "_connection_string", return_value=DATABASE_URL):
        store = PostgresStore(config)
    store.metadata.create_all(store.engine, tables=[store.capabilities_table, store.capability_questions_table])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.save_capabilities(CAPABILITIES), range(40)))

    assert len(results) == 40
    with store.engine.begin() as connection:
        ids = sorted(row.id for row in connection.execute(select(store.capabilities_table)))
        links = connection.execute(select(store.capability_questions_table)).all()
    assert ids == sorted(capability["id"] for capability in CAPABILITIES)
    assert len(links) == 24
