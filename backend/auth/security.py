"""Low-level primitives: bcrypt password hashing and JWT tokens."""
from __future__ import annotations

import os
from datetime import timedelta

import bcrypt
import jwt

from db.base import utcnow
from utils.runtime_env import is_production

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=int(os.getenv("ACCESS_TOKEN_HOURS", "12")))


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Fail loud in production; allow a dev default only outside prod.
        # (The old FLASK_ENV-only check never fired on Railway, silently
        # falling back to the forgeable dev secret.)
        if is_production():
            raise RuntimeError(
                "JWT_SECRET must be set in production. "
                "Set it in backend/.env or as a platform secret."
            )
        return "dev-insecure-secret-change-me"
    return secret


def ensure_configured() -> None:
    """Fail fast at process start when production lacks JWT_SECRET.

    Without this the guard in _secret() only fires lazily on the first
    token operation — a misconfigured deploy would boot "healthy" and then
    500 on every auth request.
    """
    _secret()


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
