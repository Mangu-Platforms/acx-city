"""Usage recording, monthly rollups, and quota math."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Organization, UsageEvent

# Global default monthly quota (characters of paid synthesis). 0 = unlimited.
DEFAULT_MONTHLY_CHAR_QUOTA = int(os.getenv("QUOTA_MONTHLY_CHARS", "0"))


class QuotaExceeded(Exception):
    """Raised when an operation would exceed an org's monthly quota."""

    def __init__(self, message: str, used: int, quota: int, requested: int = 0):
        super().__init__(message)
        self.used = used
        self.quota = quota
        self.requested = requested


def current_period(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def estimate_cost_usd(characters: int, cost_per_million_chars: float) -> float:
    return round(characters / 1_000_000 * cost_per_million_chars, 6)


def quota_for(org: Organization) -> int:
    """Effective monthly char quota for an org (0 = unlimited)."""
    if org.monthly_char_quota is not None:
        return org.monthly_char_quota
    return DEFAULT_MONTHLY_CHAR_QUOTA


def month_usage(session: Session, organization_id: str, period: Optional[str] = None) -> dict:
    """Aggregate this org's usage for the period (defaults to current month)."""
    period = period or current_period()
    row = session.execute(
        select(
            func.coalesce(func.sum(UsageEvent.characters), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
        ).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.period == period,
        )
    ).one()
    return {"period": period, "characters": int(row[0]), "cost_usd": round(float(row[1]), 6)}


def remaining_quota(session: Session, org: Organization) -> Optional[int]:
    """Chars left this month, or None if unlimited."""
    quota = quota_for(org)
    if quota <= 0:
        return None
    used = month_usage(session, org.id)["characters"]
    return max(quota - used, 0)


def check_quota(session: Session, org: Organization, requested_chars: int, paid: bool) -> None:
    """Raise QuotaExceeded if adding ``requested_chars`` would exceed the quota.

    Free providers (paid=False) never consume quota, so they always pass.
    """
    if not paid:
        return
    quota = quota_for(org)
    if quota <= 0:
        return
    used = month_usage(session, org.id)["characters"]
    if used + requested_chars > quota:
        raise QuotaExceeded(
            f"Monthly quota exceeded: {used}/{quota} chars used, requested {requested_chars}",
            used=used, quota=quota, requested=requested_chars,
        )


def record_usage(session: Session, organization_id: str, provider: str, characters: int,
                 cost_per_million_chars: float, job_id: Optional[str] = None) -> UsageEvent:
    """Append a ledger row for billable synthesis. No-op for zero-cost usage."""
    cost = estimate_cost_usd(characters, cost_per_million_chars)
    event = UsageEvent(
        organization_id=organization_id,
        job_id=job_id,
        provider=provider,
        characters=characters,
        cost_usd=cost,
        period=current_period(),
    )
    session.add(event)
    session.flush()
    return event
