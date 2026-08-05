"""Shared deployment-environment detection.

One predicate for every production-only guard (JWT secret enforcement,
webhook signature requirement, DATABASE_URL validation, storage signing
fallback) so the guards can never drift apart again.
"""
from __future__ import annotations

import os


def is_production() -> bool:
    """True on any signal that this is a deployed environment.

    FLASK_ENV alone is not enough: the Railway deploy config never sets it.
    RAILWAY_ENVIRONMENT is injected by Railway on every deploy; FLASK_DEBUG=0
    is an explicit prod signal.
    """
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("FLASK_DEBUG") == "0"
        or os.getenv("FLASK_ENV") == "production"
    )
