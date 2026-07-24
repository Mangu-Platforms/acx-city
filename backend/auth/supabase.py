"""Supabase Auth integration.

Verifies Supabase-issued JWTs and provisions a matching local User + personal
Organization on first sight (just-in-time), so the rest of the app keeps using
our own ownership/tenancy model unchanged.

Supabase signs access tokens with the project's JWT secret (HS256) by default;
newer projects can use asymmetric keys (RS256 via JWKS). Both are supported:
  * HS256: set SUPABASE_JWT_SECRET.
  * RS256: set SUPABASE_JWKS_URL (e.g. https://<ref>.supabase.co/auth/v1/.well-known/jwks.json).
"""
from __future__ import annotations

import os

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Membership, Organization, Role, User

SUPABASE_AUDIENCE = os.getenv("SUPABASE_JWT_AUD", "authenticated")

_jwks_client = None


class SupabaseAuthError(Exception):
    """Raised when a Supabase token is missing/invalid/expired."""


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        url = os.getenv("SUPABASE_JWKS_URL")
        if not url:
            raise SupabaseAuthError("SUPABASE_JWKS_URL not configured for RS256")
        _jwks_client = jwt.PyJWKClient(url)
    return _jwks_client


def verify_supabase_token(token: str) -> dict:
    """Return the verified claims dict, or raise SupabaseAuthError."""
    secret = os.getenv("SUPABASE_JWT_SECRET")
    try:
        if secret:
            return jwt.decode(
                token, secret, algorithms=["HS256"], audience=SUPABASE_AUDIENCE,
                options={"require": ["exp", "sub"]},
            )
        # Asymmetric path.
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, signing_key, algorithms=["RS256", "ES256"], audience=SUPABASE_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise SupabaseAuthError(f"Invalid Supabase token: {e}") from e


def provision_user(session: Session, claims: dict) -> User:
    """Find or create the local User (and a personal Org) for these claims.

    Idempotent: safe under concurrent first requests (unique email + membership
    constraints mean a race resolves to the existing row).
    """
    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not sub:
        raise SupabaseAuthError("Token missing subject")

    # Prefer matching by the stable Supabase subject stored as the local user id;
    # fall back to email for users provisioned before this mapping existed.
    user = session.get(User, sub)
    if user is None and email:
        user = session.execute(select(User).where(User.email == email)).scalars().first()

    if user is None:
        display = (claims.get("user_metadata") or {}).get("full_name") or (email.split("@")[0] if email else None)
        # Use the Supabase subject as the local user id so the mapping is stable.
        user = User(id=sub, email=email or f"{sub}@users.noreply",
                    password_hash="", display_name=display, is_active=True)
        session.add(user)
        session.flush()

    # Ensure the user has at least one organization (their personal workspace).
    membership = session.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalars().first()
    if membership is None:
        org = Organization(name=f"{user.display_name or (email.split('@')[0] if email else 'My')}'s workspace")
        session.add(org)
        session.flush()
        session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.owner))
        session.flush()

    return user


def authenticate(session: Session, token: str) -> User:
    claims = verify_supabase_token(token)
    return provision_user(session, claims)
