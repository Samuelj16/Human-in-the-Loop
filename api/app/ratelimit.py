"""Per-IP throttling for unauthenticated endpoints.

The per-user daily task cap protects model spend, but it only applies once
someone has an account - registration and login are reachable by anyone, so
they need their own limit or account creation is free and unbounded.

This is a single-process sliding window. It is the right amount of machinery
for one API instance; behind more than one, move the counter into Redis so the
limit is shared (the interface here does not change).

Mechanics:
  - Tracks monotonic timestamps in a `deque` per IP key.
  - Purges timestamps older than the sliding window.
  - Computes exact `Retry-After` seconds upon hitting the maximum allowed hits.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowLimiter:
    """In-memory sliding window, keyed by caller.

    Single-process by design: correct for one API instance, and the interface
    does not change when the counter moves to Redis behind several.
    """
    def __init__(self, max_hits: int, window_seconds: int) -> None:
        """Initialize sliding window rate limiter.
        
        Args:
            max_hits: Maximum permitted hits within the window duration.
            window_seconds: Duration of the rolling window in seconds.
        """
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Record a hit, raising 429 with Retry-After once the window is full.
        
        Args:
            key: Rate limiting key (typically client IP address).
            
        Raises:
            HTTPException (429): If the client exceeded the allowed hits within the window.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds
        hits = self._hits[key]

        # Evict timestamps outside the active rolling window
        while hits and hits[0] < cutoff:
            hits.popleft()

        # Reject request if capacity reached
        if len(hits) >= self.max_hits:
            retry_after = int(self.window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)

        # Opportunistic cleanup so idle keys do not accumulate forever in memory.
        if len(self._hits) > 10_000:
            for stale_key in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale_key]


def _client_ip(request: Request) -> str:
    """Extract client IP address from request headers or socket.
    
    Checks X-Forwarded-For first for reverse proxy compatibility (Railway, Vercel, Nginx),
    falling back to direct client host.
    
    Args:
        request: Incoming FastAPI request.
        
    Returns:
        str: Client IP string.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Registration is the expensive one (it creates rows); login is brute-forceable.
_register_limiter = SlidingWindowLimiter(
    max_hits=settings.rate_limit_register_per_hour, window_seconds=3600
)
_login_limiter = SlidingWindowLimiter(
    max_hits=settings.rate_limit_login_per_15_min, window_seconds=900
)


async def limit_registration(request: Request) -> None:
    """Per-IP throttle for account creation endpoint.
    
    Args:
        request: Incoming HTTP request.
    """
    if settings.rate_limit_enabled:
        _register_limiter.check(_client_ip(request))


async def limit_login(request: Request) -> None:
    """Per-IP throttle for login attempts, to blunt credential stuffing attacks.
    
    Args:
        request: Incoming HTTP request.
    """
    if settings.rate_limit_enabled:
        _login_limiter.check(_client_ip(request))

