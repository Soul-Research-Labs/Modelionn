"""Security headers middleware — defense-in-depth HTTP response headers.

Applies hardened headers to every response, following OWASP recommendations
and PIL++ patterns: prevent clickjacking, MIME-sniffing, XSS reflection,
and enforce HSTS in production.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Headers applied to every response
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",  # Modern browsers: CSP is the control
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "frame-ancestors 'none'"
    ),
}

# HSTS is only safe when deployed behind TLS
_HSTS_HEADER = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security response headers on every request."""

    def __init__(self, app, *, enable_hsts: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        if self._enable_hsts:
            response.headers["Strict-Transport-Security"] = _HSTS_HEADER
        return response
