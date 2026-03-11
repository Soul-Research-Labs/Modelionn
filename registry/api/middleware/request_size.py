"""Request size limit middleware — rejects oversized payloads early."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Return 413 if Content-Length exceeds the configured maximum."""

    def __init__(self, app, max_content_length: int = 50 * 1024 * 1024) -> None:  # noqa: ANN001
        super().__init__(app)
        self.max_content_length = max_content_length

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_content_length:
                    return JSONResponse(
                        {"detail": "Request body too large"},
                        status_code=413,
                    )
            except ValueError:
                pass  # Non-integer Content-Length — let the server handle it
        return await call_next(request)
