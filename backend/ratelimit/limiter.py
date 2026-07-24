"""Fixed-window rate limiter with pluggable backends."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # epoch seconds when the window resets
    retry_after: int  # seconds until allowed again (0 if allowed)


class RateLimiter:
    def check(self, session: Session, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        raise NotImplementedError


class NoopLimiter(RateLimiter):
    def check(self, session, key, limit, window_seconds):
        return RateLimitResult(True, limit, limit, int(time.time()) + window_seconds, 0)


class PostgresLimiter(RateLimiter):
    """Fixed-window counter kept in the rate_buckets table.

    Uses an upsert that increments atomically. On Postgres this is a single
    ``INSERT ... ON CONFLICT DO UPDATE``; on SQLite it falls back to a small
    read-modify-write (fine for single-process dev).
    """

    def check(self, session: Session, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        reset_at = window_start + window_seconds
        dialect = session.get_bind().dialect.name

        if dialect == "postgresql":
            row = session.execute(
                text(
                    "INSERT INTO rate_buckets (key, window_start, count) "
                    "VALUES (:k, :w, 1) "
                    "ON CONFLICT (key, window_start) "
                    "DO UPDATE SET count = rate_buckets.count + 1 "
                    "RETURNING count"
                ),
                {"k": key, "w": window_start},
            ).one()
            count = int(row[0])
        else:
            existing = session.execute(
                text("SELECT count FROM rate_buckets WHERE key = :k AND window_start = :w"),
                {"k": key, "w": window_start},
            ).first()
            if existing is None:
                session.execute(
                    text("INSERT INTO rate_buckets (key, window_start, count) VALUES (:k, :w, 1)"),
                    {"k": key, "w": window_start},
                )
                count = 1
            else:
                count = int(existing[0]) + 1
                session.execute(
                    text("UPDATE rate_buckets SET count = :c WHERE key = :k AND window_start = :w"),
                    {"c": count, "k": key, "w": window_start},
                )
        session.flush()

        allowed = count <= limit
        remaining = max(limit - count, 0)
        retry_after = 0 if allowed else max(reset_at - now, 1)
        return RateLimitResult(allowed, limit, remaining, reset_at, retry_after)


class UpstashLimiter(RateLimiter):
    """Upstash Redis REST fixed-window limiter (MANGU baseline for distributed limits)."""

    def __init__(self):
        self.url = os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

    def check(self, session, key, limit, window_seconds):
        import requests

        now = int(time.time())
        window_start = now - (now % window_seconds)
        reset_at = window_start + window_seconds
        rkey = f"rl:{key}:{window_start}"
        headers = {"Authorization": f"Bearer {self.token}"}
        # INCR then set expiry (pipeline via REST).
        r = requests.post(f"{self.url}/incr/{rkey}", headers=headers, timeout=5)
        count = int(r.json().get("result", 1))
        if count == 1:
            requests.post(f"{self.url}/expire/{rkey}/{window_seconds}", headers=headers, timeout=5)
        allowed = count <= limit
        remaining = max(limit - count, 0)
        retry_after = 0 if allowed else max(reset_at - now, 1)
        return RateLimitResult(allowed, limit, remaining, reset_at, retry_after)


_limiter: Optional[RateLimiter] = None


def get_limiter(force: bool = False) -> RateLimiter:
    global _limiter
    if _limiter is not None and not force:
        return _limiter
    backend = os.getenv("RATE_LIMIT_BACKEND", "postgres").lower()
    if backend in ("none", "off", "disabled"):
        _limiter = NoopLimiter()
    elif backend == "upstash":
        _limiter = UpstashLimiter()
    else:
        _limiter = PostgresLimiter()
    return _limiter


def check_rate_limit(session: Session, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    return get_limiter().check(session, key, limit, window_seconds)
