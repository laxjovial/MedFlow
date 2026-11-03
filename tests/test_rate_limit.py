"""Tests for the process-local sliding-window limiter."""
from app.server.rate_limit import SlidingWindowRateLimiter


def test_sliding_window_allows_limit_then_returns_retry_after():
    limiter = SlidingWindowRateLimiter()
    assert limiter.consume("login:ip:test", limit=2, window_seconds=10, now=100) is None
    assert limiter.consume("login:ip:test", limit=2, window_seconds=10, now=101) is None
    retry = limiter.consume("login:ip:test", limit=2, window_seconds=10, now=102)
    assert retry == 8


def test_sliding_window_expires_old_attempts():
    limiter = SlidingWindowRateLimiter()
    limiter.consume("login:ip:test", limit=1, window_seconds=10, now=100)
    assert limiter.consume("login:ip:test", limit=1, window_seconds=10, now=111) is None
