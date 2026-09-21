from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import MemoryConfig
from backend.app.main import create_app
from backend.app.models.db import get_engine, get_session_local, init_engine
from backend.app.models.entities import Base


@pytest.fixture()
def db_session() -> Generator:
    init_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(get_engine())
    session_local = get_session_local()
    with session_local() as db:
        yield db


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """FastAPI test client with in-memory SQLite and memory init skipped."""
    disabled = MemoryConfig(enabled=False)
    with patch('backend.app.main.load_memory_config', return_value=disabled):
        app = create_app('sqlite+pysqlite:///:memory:')
        with TestClient(app) as test_client:
            yield test_client
