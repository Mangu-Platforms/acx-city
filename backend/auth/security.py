"""Low-level primitives: bcrypt password hashing and JWT tokens."""
from __future__ import annotations

import os
from datetime import timedelta

import bcrypt
import jwt

from db.base import utcnow

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=int(os.getenv("ACCESS_TOKEN_HOURS", "12")))


def _is_production() -> bool:
    """True on any signal that this is a deployed environment.

    FLASK_ENV alone is not enough: the Railway deploy config never sets it,
    so the old FLASK_ENV-only guard could silently fall back to the dev
    secret in production (forgeable tokens). RAILWAY_ENVIRONMENT is injected
    by Railway on every deploy; FLASK_DEBUG=0 is an explicit prod signal.
    """
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("FLASK_DEBUG") == "0"
        or os.getenv("FLASK_ENV") == "production"
    )


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Fail loud in production; allow a dev default only outside prod.
        if _is_production():
            raise RuntimeError(
                "JWT_SECRET must be set in production. "
                "Set it in backend/.env or as a platform secret."
            )
        return "dev-insecure-secret-change-me"
    return secret


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, extra: dict | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on any invalid/expired token."""
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
