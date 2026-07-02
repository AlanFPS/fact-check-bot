from factcheckbot.rate_limit import RateLimiter
from factcheckbot.seen_store import SeenStore


def test_per_user_limit_blocks_only_that_user():
    now = 1000.0
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, per_user_per_hour=2, global_per_hour=10, now=lambda: now)

    limiter.record("alice")
    limiter.record("alice")

    assert limiter.allow("alice") == (False, "per-user rate limit")
    assert limiter.allow("bob") == (True, "")
    store.close()


def test_global_limit_blocks_fresh_user():
    now = 1000.0
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, per_user_per_hour=10, global_per_hour=2, now=lambda: now)

    limiter.record("alice")
    limiter.record("bob")

    assert limiter.allow("carol") == (False, "global rate limit")
    store.close()


def test_window_rolls_forward():
    current = 1000.0
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, per_user_per_hour=1, global_per_hour=10, now=lambda: current)

    limiter.record("alice")
    assert limiter.allow("alice") == (False, "per-user rate limit")

    current += 3601
    assert limiter.allow("alice") == (True, "")
    store.close()
