"""Transient provider failures must not throw away a whole research run."""
import pytest

from app.llm.base import LLMError, LLMTransientError
from app.llm.retry import with_retry


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Keep the tests fast without weakening what they assert."""

    async def instant(_seconds):
        return None

    monkeypatch.setattr("app.llm.retry.asyncio.sleep", instant)


async def test_succeeds_first_time_without_retrying():
    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        return "ok"

    result, attempts = await with_retry(op)

    assert result == "ok"
    assert attempts == 1
    assert calls["n"] == 1


async def test_retries_transient_failure_then_succeeds():
    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMTransientError("overloaded")
        return "recovered"

    result, attempts = await with_retry(op)

    assert result == "recovered"
    assert attempts == 3, "attempt count is recorded as telemetry"


async def test_gives_up_after_the_attempt_limit():
    async def op():
        raise LLMTransientError("still overloaded")

    with pytest.raises(LLMTransientError):
        await with_retry(op, max_attempts=3)


async def test_fatal_errors_are_not_retried():
    """A bad request will fail identically every time; retrying just burns time."""
    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        raise LLMError("invalid request")

    with pytest.raises(LLMError):
        await with_retry(op)

    assert calls["n"] == 1


async def test_server_stated_delay_is_honoured(monkeypatch):
    """A 429 that says "retry in 31s" must not be retried after 2s.

    Free-tier quotas reset on a fixed window, so retrying early just burns
    another attempt on the same rejection.
    """
    slept: list[float] = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr("app.llm.retry.asyncio.sleep", record)

    calls = {"n": 0}

    async def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMTransientError("rate limited", retry_after=31.0)
        return "ok"

    result, attempts = await with_retry(op)

    assert result == "ok" and attempts == 2
    assert slept and slept[0] >= 31.0, f"waited only {slept[0]:.1f}s"


async def test_server_stated_delay_is_capped():
    """An absurd server delay must not hang the worker indefinitely."""
    from app.llm.retry import SERVER_DELAY_CAP_SECONDS

    assert SERVER_DELAY_CAP_SECONDS <= 120
