from collections.abc import Generator

import pytest

from backend.app.models.db import get_engine, get_session_local, init_engine
from backend.app.models.entities import Base


@pytest.fixture()
def db_session() -> Generator:
    init_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(get_engine())
    session_local = get_session_local()
    with session_local() as db:
        yield db
