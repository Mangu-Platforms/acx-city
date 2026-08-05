"""Engine + session management.

DATABASE_URL selects the backend. Examples:
    postgresql+psycopg://user:pass@host:5432/audiobook   (production)
    sqlite:///./local.db                                  (local/sandbox)

The engine is created lazily so importing this module never requires a live DB.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None

DEFAULT_URL = "sqlite:///./audiobook.db"


def _normalize_url(url: str) -> str:
    # Accept the common "postgres://" and "postgresql://" forms and route them
    # through the psycopg (v3) driver we depend on.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def database_url() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        # An empty string used to reach SQLAlchemy and die with the cryptic
        # "Could not parse URL from ''". Treat empty/unset as "use SQLite"
        # in dev, but fail fast in production: there it means a broken or
        # missing Railway reference variable, and silently writing to
        # container-local SQLite would lose data on the next deploy.
        from utils.runtime_env import is_production

        if is_production():
            raise RuntimeError(
                "DATABASE_URL is missing or empty. Set it to the Postgres URL "
                "(Railway reference variable ${{Postgres.DATABASE_URL}}); "
                "local SQLite is only used in development."
            )
        return DEFAULT_URL
    return _normalize_url(raw)


def is_postgres() -> bool:
    return database_url().startswith("postgresql")


def init_engine(url: Optional[str] = None, echo: bool = False) -> Engine:
    """Create (or recreate) the global engine. Safe to call in tests."""
    global _engine, _SessionFactory
    url = _normalize_url(url) if url else database_url()

    connect_args = {}
    kwargs = {"echo": echo, "future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Needed so the same in-memory/file DB is usable across threads (worker + api).
        connect_args["check_same_thread"] = False

    _engine = create_engine(url, connect_args=connect_args, **kwargs)

    if url.startswith("sqlite"):
        # Enforce foreign keys on SQLite (off by default) so ownership FKs behave.
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session() -> Session:
    if _SessionFactory is None:
        init_engine()
    assert _SessionFactory is not None
    return _SessionFactory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
