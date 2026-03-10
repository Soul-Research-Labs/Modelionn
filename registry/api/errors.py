"""Standardized error responses — uniform error envelope for the API.

Every error response follows the structure:
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Artifact not found",
    "details": {...},        # optional
    "request_id": "abc123"   # from RequestIDMiddleware
  }
}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from registry.api.middleware.request_id import request_id_ctx

# Map HTTP status codes to canonical error codes
_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


def _error_envelope(
    status: int,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Build a standardized error response."""
    body: dict[str, Any] = {
        "error": {
            "code": _STATUS_CODES.get(status, "ERROR"),
            "message": message,
            "request_id": request_id_ctx.get(""),
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


async def _starlette_http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette-level HTTP errors (e.g., 404 for unregistered routes)."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _error_envelope(exc.status_code, detail)


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI/Starlette HTTPExceptions with uniform envelope."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _error_envelope(exc.status_code, detail)


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic/FastAPI validation errors with field-level details."""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        })
    return _error_envelope(422, "Validation error", details=errors)


async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — never leak internals."""
    import logging as _logging
    _logging.getLogger(__name__).exception(
        "Unhandled exception in %s %s", request.method, request.url.path,
    )
    return _error_envelope(500, "Internal server error")


async def _pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Handle raw Pydantic ValidationErrors raised in route bodies."""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        })
    return _error_envelope(422, "Validation error", details=errors)


def register_error_handlers(app: FastAPI) -> None:
    """Install all custom exception handlers on the FastAPI app."""
    app.add_exception_handler(StarletteHTTPException, _starlette_http_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, _pydantic_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _generic_error_handler)  # type: ignore[arg-type]
