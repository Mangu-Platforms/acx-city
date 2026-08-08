"""Cost ledger + quota accounting.

Records billable synthesis as UsageEvent rows and answers "how much has this org
used this month" for quota enforcement. Free providers (Edge) cost nothing and
do not count against quota.
"""
from .usage import (
    QuotaExceeded,
    current_period,
    estimate_cost_usd,
    mark_stage,
    month_usage,
    quota_for,
    record_usage,
    remaining_quota,
    stage_done,
)

__all__ = [
    "QuotaExceeded",
    "current_period",
    "estimate_cost_usd",
    "mark_stage",
    "month_usage",
    "quota_for",
    "record_usage",
    "remaining_quota",
    "stage_done",
]
