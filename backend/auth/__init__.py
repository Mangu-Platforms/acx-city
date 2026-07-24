"""Authentication & tenancy: password hashing, JWT sessions, and the request
guard that resolves the current user + organization and enforces ownership.
"""
from .security import hash_password, verify_password, create_access_token, decode_token
from .service import signup, login, AuthError
from .guard import (
    require_auth,
    current_identity,
    Identity,
    resolve_org,
    AuthzError,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
    "signup",
    "login",
    "AuthError",
    "require_auth",
    "current_identity",
    "Identity",
    "resolve_org",
    "AuthzError",
]
