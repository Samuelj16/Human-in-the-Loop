"""Shared retry policy for transient provider failures.

Handles exponential backoff with full random jitter to mitigate thundering herds
when remote model APIs experience rate limits, transient overload (HTTP 529/503),
or dropped connections.

Key Features:
  - Caps maximum retry attempts (`MAX_ATTEMPTS = 4`).
  - Bounds retry delay to `MAX_DELAY_SECONDS = 20.0
# A server-stated delay may legitimately exceed our own cap (free-tier quotas
# reset on the minute), but not without bound.
SERVER_DELAY_CAP_SECONDS = 65.0`.
  - Injects randomized multiplicative jitter (0.5x to 1.5x).
  - Returns total attempts along with the result for turn-level telemetry logging.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.llm.base import LLMTransientError

log = logging.getLogger(__name__)

T = TypeVar("T")

# Maximum retry attempts before giving up and failing the turn
MAX_ATTEMPTS = 4
# Base exponential backoff factor in seconds
BASE_DELAY_SECONDS = 1.0
# Upper bound cap on backoff sleep duration
MAX_DELAY_SECONDS = 20.0
# A server-stated delay may legitimately exceed our own cap (free-tier quotas
# reset on the minute), but not without bound.
SERVER_DELAY_CAP_SECONDS = 65.0


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = MAX_ATTEMPTS,
    label: str = "llm call",
) -> tuple[T, int]:
    """Run `operation`, retrying transient failures with jittered exponential backoff.

    Returns the result and how many attempts it took, so the attempt count can
    be recorded as telemetry rather than vanishing into a log line.
    
    Args:
        operation: Async callable returning a value.
        max_attempts: Maximum attempts before raising.
        label: Context string for log warning messages.
        
    Returns:
        tuple[T, int]: Result value and total attempt count (1..max_attempts).
        
    Raises:
        LLMTransientError: If all retry attempts fail.
    """
    last: LLMTransientError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation(), attempt
        except LLMTransientError as exc:
            last = exc
            if attempt == max_attempts:
                break
            # Calculate exponential backoff with jitter
            delay = min(BASE_DELAY_SECONDS * 2 ** (attempt - 1), MAX_DELAY_SECONDS)
            delay *= 0.5 + random.random()  # jitter: avoid a retry thundering herd

            # A server that tells us when to come back knows better than our
            # curve does - a free-tier quota resets on a fixed window, and
            # retrying early just burns another attempt on the same 429.
            stated = getattr(exc, "retry_after", None)
            if stated:
                delay = max(delay, min(float(stated) + 1.0, SERVER_DELAY_CAP_SECONDS))
            log.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                label, attempt, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)

    raise LLMTransientError(
        f"{label} failed after {max_attempts} attempts: {last}"
    ) from last

