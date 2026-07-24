"""Database package: engine, session management, and ORM models.

This is the durable system-of-record that replaces the in-memory ``active_tasks``
dict. Postgres is the production target; the code is written Postgres-first
(e.g. the job queue uses ``FOR UPDATE SKIP LOCKED``). A SQLite URL is accepted
for local/sandbox use, with concurrency-sensitive behavior degraded gracefully.
"""
from .base import Base
from .session import (
    get_engine,
    get_session,
    session_scope,
    init_engine,
    is_postgres,
)

__all__ = [
    "Base",
    "get_engine",
    "get_session",
    "session_scope",
    "init_engine",
    "is_postgres",
]
