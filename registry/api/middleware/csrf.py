"""CSRF origin validation middleware.

Protects state-changing requests (POST, PUT, PATCH, DELETE) by verifying
that the ``Origin`` or ``Referer`` header matches the server host.
API-only clients using ``Authorization: Bearer`` are exempt since they
are not vulnerable to cross-site request forgery.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate Origin/Referer on state-changing requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        # API key / Bearer auth is not CSRF-vulnerable (no cookies involved)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return await call_next(request)

        # Check Origin or Referer
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            origin_host = urlparse(origin).netloc.split(":")[0]
            # Derive expected host from Host header
            host_header = request.headers.get("host", "")
            expected_host = host_header.split(":")[0]
            if origin_host and expected_host and origin_host != expected_host:
                logger.warning(
                    "CSRF blocked: origin=%s host=%s path=%s",
                    origin, host_header, request.url.path,
                )
                return JSONResponse(
                    {"detail": "Cross-origin request blocked"},
                    status_code=403,
                )

        return await call_next(request)
