"""Flask request guard: authenticate the bearer token, resolve the current
user and their active organization, and provide org-scoping helpers so every
resource access is authorized by membership rather than by resource id.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import wraps
from typing import Optional

import jwt
from flask import g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Membership, Organization, User
from .security import decode_token


def _auth_mode() -> str:
    # "supabase" verifies Supabase-issued JWTs; "legacy" uses our bcrypt/JWT path.
    return os.getenv("AUTH_MODE", "legacy").lower()


class AuthzError(Exception):
    """Raised when an authenticated user is not permitted to access a resource."""


@dataclass
class Identity:
    user: User
    org: Organization
    role: str


def _extract_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _resolve_user_and_org_claim(session: Session, token: str) -> tuple[User, Optional[str]]:
    """Return (user, org_claim) from the token, using the configured AUTH_MODE.

    Supabase mode verifies a Supabase JWT and provisions the user just-in-time;
    legacy mode decodes our own JWT and looks the user up.
    """
    if _auth_mode() == "supabase":
        from .supabase import SupabaseAuthError, authenticate

        try:
            user = authenticate(session, token)
        except SupabaseAuthError as e:
            raise AuthzError(str(e))
        return user, None  # Supabase tokens don't carry our org claim

    # Legacy path.
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise AuthzError("Invalid or expired token")
    user_id = payload.get("sub")
    user = session.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise AuthzError("User not found or inactive")
    return user, payload.get("org")


def _load_identity(session: Session) -> Identity:
    token = _extract_token()
    if not token:
        raise AuthzError("Missing bearer token")

    user, org_claim = _resolve_user_and_org_claim(session, token)
    if not user.is_active:
        raise AuthzError("User not found or inactive")

    # Active org: prefer an explicit X-Org-Id header, else the token's org claim,
    # else the user's first membership. Membership is always verified.
    requested_org = request.headers.get("X-Org-Id") or org_claim
    membership = None
    if requested_org:
        membership = session.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == requested_org,
            )
        ).scalars().first()
    if membership is None:
        membership = session.execute(
            select(Membership).where(Membership.user_id == user.id)
        ).scalars().first()
    if membership is None:
        raise AuthzError("User has no organization membership")

    org = session.get(Organization, membership.organization_id)
    return Identity(user=user, org=org, role=membership.role.value)


def require_auth(fn):
    """Decorator: rejects unauthenticated requests; stashes Identity on g.

    The wrapped view is expected to use a request-scoped session available via
    ``g.db`` (set by the app's before_request), so the guard reuses it.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        session: Session = g.db
        try:
            g.identity = _load_identity(session)
            # Persist any just-in-time user/org provisioning (Supabase mode) so it
            # survives even on read-only endpoints that never commit themselves.
            if _auth_mode() == "supabase":
                session.commit()
        except AuthzError as e:
            session.rollback()
            return jsonify({"error": str(e)}), 401
        return fn(*args, **kwargs)

    return wrapper


def current_identity() -> Identity:
    return g.identity


def resolve_org(session: Session, identity: Identity, organization_id: str) -> None:
    """Assert the identity may act within organization_id (defense in depth)."""
    if organization_id != identity.org.id:
        membership = session.execute(
            select(Membership).where(
                Membership.user_id == identity.user.id,
                Membership.organization_id == organization_id,
            )
        ).scalars().first()
        if membership is None:
            raise AuthzError("Not a member of that organization")
