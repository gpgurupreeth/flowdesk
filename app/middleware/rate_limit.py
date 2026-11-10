
"""Simple in-memory rate limiter for authentication endpoints.

Uses a sliding-window counter per IP+endpoint. Not suitable for
multi-server deployments without a shared store (e.g. Redis), but
adequate for a single-instance portfolio application.
"""

import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse


class RateLimiter:
    """Token-bucket / sliding-window rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key -> list of timestamps
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds

        # Prune old hits
        hits = [t for t in self._hits.get(key, []) if t > window_start]

        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            return False

        hits.append(now)
        self._hits[key] = hits
        return True


# One limiter for auth endpoints: 10 requests per minute per IP.
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


async def rate_limit_middleware(
    request: Request,
    call_next: Callable,
) -> Response:
    """Apply rate limiting to authentication endpoints only."""
    path = request.url.path

    # Only rate limit auth endpoints
    if not path.startswith("/api/auth/"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{path}"

    if not auth_rate_limiter.is_allowed(key):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Too many requests. Please try again later."
            },
        )

    return await call_next(request)
