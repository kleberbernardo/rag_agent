"""Rate limiting: a ceiling per caller, so one client cannot spend the budget.

Without this, a client in a retry loop asks a thousand questions a minute and
every one of them is a paid call to a model provider. The first sign is the
invoice.

The limit is per caller, not per process. A caller is its API key when there is
one and its address when there is not, because a service behind a shared key
still wants one client's loop to be one client's problem.

## Why not slowapi

slowapi is the usual answer for FastAPI and it does not work here. Both of its
middlewares find the route by walking `app.routes` looking for something with
an `.endpoint`, and current FastAPI wraps everything registered through
`include_router` in an `_IncludedRouter` that has none. Every request therefore
looks like a route it cannot identify, which it treats as exempt, and nothing
is ever limited. That failure is silent: the limiter reports itself enabled and
the ceiling never fires.

What is used instead is `limits`, the library slowapi is built on, and the same
one behind flask-limiter. It is the primitive rather than a smaller wrapper of
it, and the wrapper is what was broken.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware

from rag_agent.api.security import API_KEY_HEADER
from rag_agent.config import get_settings

logger = logging.getLogger(__name__)

# Probes are never limited. A load balancer polling readiness every two seconds
# would exhaust a per-minute budget on its own, and the first instance taken
# out of rotation would be a healthy one.
EXEMPT_PATHS = frozenset({"/health", "/ready", "/docs", "/redoc", "/openapi.json"})

_REFUSED = "Limite de {limit} excedido. Tente novamente em {seconds}s."


def identify(request: Request) -> str:
    """Who is being limited.

    The key is hashed rather than used as-is: this string becomes a storage
    key and can reach a log, and a credential belongs in neither.
    """
    presented = request.headers.get(API_KEY_HEADER)
    if presented:
        return "key:" + hashlib.sha256(presented.encode()).hexdigest()[:16]

    client = request.client
    return f"ip:{client.host}" if client else "ip:desconhecido"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """One moving window per caller.

    A moving window rather than a fixed one: with a fixed window a caller
    spends the whole budget in the last second of one minute and the whole
    budget again in the first second of the next, which is twice the ceiling
    at the moment it matters least.

    The storage is per process. Several replicas therefore enforce the ceiling
    several times over, which is the usual first step and the reason `limits`
    also speaks Redis: pointing this at the Redis already in the compose file
    is a constructor argument, not a rewrite.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        super().__init__(app)

        settings = get_settings()
        configured = settings.rate_limit.strip()

        self.item: RateLimitItem | None = parse(configured) if configured else None
        self.limiter = MovingWindowRateLimiter(MemoryStorage())

        if self.item:
            logger.info("Rate limit: %s per caller", self.item)
        else:
            logger.info("Rate limit disabled.")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self.item is None or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        caller = identify(request)

        if not self.limiter.hit(self.item, caller):
            return self._refuse(caller)

        response = await call_next(request)

        return self._with_headers(response, caller)

    def _refuse(self, caller: str) -> JSONResponse:
        """429, with the wait in a header a client can obey without parsing prose."""
        assert self.item is not None
        seconds = self._seconds_until_reset(caller)

        logger.info("Rate limit hit by %s", caller)

        return JSONResponse(
            status_code=429,
            content={
                "detail": _REFUSED.format(limit=self.item, seconds=seconds),
                "reason": "rate_limit",
            },
            headers={"Retry-After": str(seconds), **self._headers(caller)},
        )

    def _with_headers(self, response: Response, caller: str) -> Response:
        """Say how much is left on every answer.

        A client that can see the remaining budget slows down before being
        refused, which is cheaper for both sides than finding out at 429.
        """
        response.headers.update(self._headers(caller))
        return response

    def _headers(self, caller: str) -> dict[str, str]:
        assert self.item is not None
        stats = self.limiter.get_window_stats(self.item, caller)

        return {
            "X-RateLimit-Limit": str(self.item.amount),
            "X-RateLimit-Remaining": str(stats.remaining),
            "X-RateLimit-Reset": str(int(stats.reset_time)),
        }

    def _seconds_until_reset(self, caller: str) -> int:
        import time

        assert self.item is not None
        stats = self.limiter.get_window_stats(self.item, caller)

        return max(1, int(stats.reset_time - time.time()))
