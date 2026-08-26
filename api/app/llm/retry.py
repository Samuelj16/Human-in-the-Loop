"""Shared retry policy for transient provider failures."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.llm.base import LLMTransientError

log = logging.getLogger(__name__)

T = TypeVar("T")

MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 20.0


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = MAX_ATTEMPTS,
    label: str = "llm call",
) -> tuple[T, int]:
    """Run `operation`, retrying transient failures with jittered backoff.

    Returns the result and how many attempts it took, so the attempt count can
    be recorded as telemetry rather than vanishing into a log line.
    """
    last: LLMTransientError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation(), attempt
        except LLMTransientError as exc:
            last = exc
            if attempt == max_attempts:
                break
            delay = min(BASE_DELAY_SECONDS * 2 ** (attempt - 1), MAX_DELAY_SECONDS)
            delay *= 0.5 + random.random()  # jitter: avoid a retry thundering herd
            log.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                label, attempt, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)

    raise LLMTransientError(
        f"{label} failed after {max_attempts} attempts: {last}"
    ) from last
