from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import get_settings

_engine = None
_SessionLocal = None


def init_engine(database_url: str | None = None) -> None:
    global _engine, _SessionLocal
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    poolclass = StaticPool if url.startswith("sqlite") else None
    _engine = create_engine(url, connect_args=connect_args, poolclass=poolclass)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def get_session_local():
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()
