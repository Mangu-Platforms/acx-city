"""Signup / login use-cases. On signup a personal organization is created and
the user is made its owner, so every user always has at least one workspace.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Membership, Organization, Role, User
from .security import create_access_token, hash_password, verify_password


class AuthError(Exception):
    """Raised for signup/login failures (bad credentials, duplicate email)."""


def signup(session: Session, email: str, password: str, display_name: str | None = None,
           org_name: str | None = None) -> tuple[User, Organization, str]:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AuthError("A valid email is required")
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters")

    existing = session.execute(select(User).where(User.email == email)).scalars().first()
    if existing:
        raise AuthError("An account with that email already exists")

    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    session.add(user)
    session.flush()

    org = Organization(name=org_name or f"{display_name or email.split('@')[0]}'s workspace")
    session.add(org)
    session.flush()

    session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.owner))
    session.flush()

    token = create_access_token(user.id, extra={"org": org.id})
    return user, org, token


def login(session: Session, email: str, password: str) -> tuple[User, str]:
    email = (email or "").strip().lower()
    user = session.execute(select(User).where(User.email == email)).scalars().first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        # Same message either way — don't leak which emails exist.
        raise AuthError("Invalid email or password")

    default_org = session.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalars().first()
    extra = {"org": default_org.organization_id} if default_org else {}
    token = create_access_token(user.id, extra=extra)
    return user, token
