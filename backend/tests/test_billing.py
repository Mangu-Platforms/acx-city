"""Cost ledger + quota math."""
import pytest

from billing import usage as u
from db import models as m
from db.session import session_scope


def _org(session, quota=None):
    org = m.Organization(name="O", monthly_char_quota=quota)
    session.add(org)
    session.flush()
    return org


def test_record_and_rollup(engine):
    with session_scope() as s:
        org = _org(s)
        u.record_usage(s, org.id, "polly", 300, 16.0)
        u.record_usage(s, org.id, "polly", 200, 16.0)
        mu = u.month_usage(s, org.id)
    assert mu["characters"] == 500
    assert mu["cost_usd"] == u.estimate_cost_usd(500, 16.0)


def test_quota_allows_and_blocks(engine):
    with session_scope() as s:
        org = _org(s, quota=1000)
        u.record_usage(s, org.id, "polly", 500, 16.0)
        # 400 more is fine
        u.check_quota(s, org, 400, paid=True)
        # 600 more exceeds
        with pytest.raises(u.QuotaExceeded):
            u.check_quota(s, org, 600, paid=True)


def test_free_provider_never_blocked(engine):
    with session_scope() as s:
        org = _org(s, quota=10)
        # Free provider ignores quota entirely.
        u.check_quota(s, org, 10_000_000, paid=False)


def test_unlimited_when_quota_zero(engine):
    with session_scope() as s:
        org = _org(s, quota=0)
        assert u.remaining_quota(s, org) is None
        u.check_quota(s, org, 10_000_000, paid=True)  # no raise
