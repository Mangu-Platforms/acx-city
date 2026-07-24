"""Rate limiting.

A small interface with two backends, selected by RATE_LIMIT_BACKEND:
  * postgres (default) — fixed-window counter in the rate_buckets table. No extra
    infra; correct for modest volume.
  * upstash — Upstash Redis REST (per the MANGU baseline) for distributed limits.
  * none — disabled (always allowed).
"""
from .limiter import RateLimitResult, check_rate_limit, get_limiter

__all__ = ["RateLimitResult", "check_rate_limit", "get_limiter"]
