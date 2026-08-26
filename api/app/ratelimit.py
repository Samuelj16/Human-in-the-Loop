"""Per-IP throttling for unauthenticated endpoints.

The per-user daily task cap protects model spend, but it only applies once
someone has an account - registration and login are reachable by anyone, so
they need their own limit or account creation is free and unbounded.

This is a single-process sliding window. It is the right amount of machinery
for one API instance; behind more than one, move the counter into Redis so the
limit is shared (the interface here does not change).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowLimiter:
    def __init__(self, max_hits: int, window_seconds: int) -> None:
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        hits = self._hits[key]

        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.max_hits:
            retry_after = int(self.window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)

        # Opportunistic cleanup so idle keys do not accumulate forever.
        if len(self._hits) > 10_000:
            for stale_key in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale_key]


def _client_ip(request: Request) -> str:
    # Railway/Vercel/most proxies set X-Forwarded-For; take the original client.
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
    if settings.rate_limit_enabled:
        _register_limiter.check(_client_ip(request))


async def limit_login(request: Request) -> None:
    if settings.rate_limit_enabled:
        _login_limiter.check(_client_ip(request))
