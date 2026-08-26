"""The limiter is unit-tested directly; the suite runs with it disabled."""
import pytest
from fastapi import HTTPException

from app.ratelimit import SlidingWindowLimiter


def test_allows_up_to_the_limit():
    limiter = SlidingWindowLimiter(max_hits=3, window_seconds=60)
    for _ in range(3):
        limiter.check("1.2.3.4")


def test_blocks_past_the_limit():
    limiter = SlidingWindowLimiter(max_hits=2, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")

    with pytest.raises(HTTPException) as exc:
        limiter.check("1.2.3.4")

    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_limits_are_per_key():
    limiter = SlidingWindowLimiter(max_hits=1, window_seconds=60)
    limiter.check("1.1.1.1")
    limiter.check("2.2.2.2")  # a different IP is unaffected

    with pytest.raises(HTTPException):
        limiter.check("1.1.1.1")


def test_window_slides(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.ratelimit.time.monotonic", lambda: clock["now"])

    limiter = SlidingWindowLimiter(max_hits=1, window_seconds=60)
    limiter.check("1.1.1.1")

    with pytest.raises(HTTPException):
        limiter.check("1.1.1.1")

    clock["now"] += 61  # the old hit has aged out
    limiter.check("1.1.1.1")
