"""Rate limiter (Postgres fixed-window backend)."""
from db.session import session_scope
from ratelimit.limiter import PostgresLimiter


def test_fixed_window_allows_then_blocks(engine):
    limiter = PostgresLimiter()
    results = []
    with session_scope() as s:
        for _ in range(5):
            results.append(limiter.check(s, "k1", limit=3, window_seconds=3600))
    allowed = [r.allowed for r in results]
    assert allowed == [True, True, True, False, False]
    assert results[0].remaining == 2
    assert results[3].retry_after > 0


def test_separate_keys_independent(engine):
    limiter = PostgresLimiter()
    with session_scope() as s:
        a = limiter.check(s, "orgA", limit=1, window_seconds=3600)
        b = limiter.check(s, "orgB", limit=1, window_seconds=3600)
    assert a.allowed and b.allowed  # different keys don't share the budget
