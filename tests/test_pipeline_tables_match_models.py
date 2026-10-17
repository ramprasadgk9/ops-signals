"""QA-30: the analysis pipeline writes through its own table definitions and leaves columns with a
database default unset, but the backend builds the database from its models, which had no such
defaults; saving any analysis failed on a database the backend created (Helm without sql/init.sql)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.app.models.entities import Base
from intelligence.storage.postgres_store import PostgresStore


def test_every_default_the_pipeline_relies_on_is_in_the_models() -> None:
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with patch.object(PostgresStore, "_connection_string", return_value="sqlite+pysqlite:///:memory:"):
        store = PostgresStore(config)

    missing = [
        f"{table.name}.{column.name}"
        for table in store.metadata.sorted_tables
        if table.name in Base.metadata.tables
        for column in table.columns
        if column.server_default is not None
        and column.name in Base.metadata.tables[table.name].c
        and Base.metadata.tables[table.name].c[column.name].server_default is None
    ]
    assert missing == []
