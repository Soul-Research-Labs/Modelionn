"""Request-ID middleware — trace every request with a unique identifier.

Generates a UUID4 request ID for each request and:
- Stores it in a ContextVar (available to all downstream code and logging)
- Returns it in the X-Request-ID response header
- Accepts an inbound X-Request-ID to chain across services
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ContextVar for request-scoped ID — accessible from any async code
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject and propagate X-Request-ID on every request/response."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        # Accept from upstream proxy, or generate a fresh one
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_ctx.reset(token)
