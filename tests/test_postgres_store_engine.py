"""PostgresStore shares one engine (one connection pool) per database URL.

Every analysis builds a store: each CSV upload, Prometheus run and OTLP (service, metric) group.
Each used to create its own engine and pool and never close it, so an OTLP cycle over a real
Collector's hundreds of metric groups ran Postgres out of connections ("too many clients")."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from intelligence.storage import postgres_store
from intelligence.storage.postgres_store import PostgresStore

_CONFIG = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))


def _store(url: str) -> PostgresStore:
    with patch.object(PostgresStore, "_connection_string", return_value=url):
        return PostgresStore(_CONFIG)


def test_stores_for_the_same_database_share_one_engine(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    stores = [_store(url) for _ in range(50)]

    assert len({id(store.engine) for store in stores}) == 1


def test_different_databases_get_different_engines(tmp_path: Path) -> None:
    assert _store(f"sqlite:///{tmp_path / 'a.db'}").engine is not _store(f"sqlite:///{tmp_path / 'b.db'}").engine


def test_in_memory_sqlite_stays_one_database_per_store() -> None:
    # Each in-memory store is its own fresh database, which tests rely on; sharing would leak rows
    # between them.
    assert _store("sqlite:///:memory:").engine is not _store("sqlite:///:memory:").engine


def test_a_shared_engine_checks_connections_before_use(tmp_path: Path) -> None:
    # A pooled connection the database closed (restart, idle timeout) is replaced, not failed on.
    assert _store(f"sqlite:///{tmp_path / 'ping.db'}").engine.pool._pre_ping is True


def test_the_shared_engine_is_reused_after_a_store_disposes_it(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'dispose.db'}"
    first = _store(url)
    first.engine.dispose()

    assert _store(url).engine is first.engine
    assert postgres_store._shared_engines[url] is first.engine
