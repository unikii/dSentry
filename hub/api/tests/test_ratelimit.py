import time

from app.services.ratelimit import LoginRateLimiter


def test_blocks_after_max_failures():
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60)

    assert limiter.retry_after("k") == 0.0
    limiter.record_failure("k")
    limiter.record_failure("k")
    assert limiter.record_failure("k") > 0
    assert limiter.retry_after("k") > 0


def test_reset_clears_failures():
    limiter = LoginRateLimiter(max_failures=2, window_seconds=60)
    limiter.record_failure("k")
    limiter.record_failure("k")
    assert limiter.retry_after("k") > 0

    limiter.reset("k")
    assert limiter.retry_after("k") == 0.0
    limiter.record_failure("k")
    assert limiter.retry_after("k") == 0.0


def test_failures_expire_after_window():
    limiter = LoginRateLimiter(max_failures=1, window_seconds=0.05)
    limiter.record_failure("k")
    assert limiter.retry_after("k") > 0

    time.sleep(0.06)
    assert limiter.retry_after("k") == 0.0


def test_keys_are_independent():
    limiter = LoginRateLimiter(max_failures=2, window_seconds=60)
    limiter.record_failure("ip1|alice")
    limiter.record_failure("ip1|alice")
    assert limiter.retry_after("ip1|alice") > 0
    assert limiter.retry_after("ip1|bob") == 0.0
    assert limiter.retry_after("ip2|alice") == 0.0


def test_sweep_keeps_memory_bounded():
    limiter = LoginRateLimiter(max_failures=1, window_seconds=60, max_keys=10)
    for i in range(100):
        limiter.record_failure(f"key-{i}")
    assert len(limiter._failures) <= 10
    # The most recent key must still be tracked.
    assert limiter.retry_after("key-99") > 0
