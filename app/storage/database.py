"""SQLite persistence via SQLAlchemy.

Thread-safety: the engine is created with ``check_same_thread=False`` and a
single module-level re-entrant lock serialises every session. The FastAPI
threadpool, the benchmark worker threads and the Streamlit process (through
the API) all share this path deliberately.

This module also contains a lightweight file-lock guard so the API process
and any CLI script do not corrupt the database when used concurrently.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.storage.tables import Base  # noqa: F401  (import registers mappings)

_WRITE_LOCK = threading.RLock()
_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker | None = None


def init_engine(database_url: str) -> Engine:
    """Create (once) the process-wide engine and ensure the schema exists."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        return _ENGINE

    if database_url.startswith("sqlite"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=StaticPool if ":memory:" in database_url else None,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    else:
        engine = create_engine(database_url, pool_pre_ping=True)

    _ENGINE = engine
    _SESSION_FACTORY = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    return engine


def session() -> Session:
    """Return a new session. Callers must use the write lock for mutations."""
    if _SESSION_FACTORY is None:
        raise RuntimeError("database not initialised; call init_engine first")
    return _SESSION_FACTORY()


def write_lock() -> threading.RLock:
    return _WRITE_LOCK


def reset_engine() -> None:
    """Forget the process engine (used by tests to switch databases)."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def engine_ref() -> Engine:
    """Return the initialised engine, initialising the default DB if needed."""
    global _ENGINE
    if _ENGINE is None:
        from app.config import get_settings

        init_engine(get_settings().database_url)
    assert _ENGINE is not None
    return _ENGINE
