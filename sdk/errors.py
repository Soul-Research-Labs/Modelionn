"""SDK error hierarchy — typed exceptions for Modelionn API errors."""

from __future__ import annotations


class ModelionnError(Exception):
    """Base exception for all Modelionn SDK errors."""

    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class AuthError(ModelionnError):
    """Authentication or authorization failure (401/403)."""
    pass


class NotFoundError(ModelionnError):
    """Requested resource not found (404)."""
    pass


class RateLimitError(ModelionnError):
    """Rate limit exceeded (429)."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None, **kwargs) -> None:
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class ValidationError(ModelionnError):
    """Request validation failed (422)."""
    pass


class ServerError(ModelionnError):
    """Server-side error (5xx)."""
    pass


def raise_for_status(status_code: int, detail: str = "") -> None:
    """Raise the appropriate typed error for an HTTP status code."""
    if 200 <= status_code < 300:
        return
    if status_code == 401 or status_code == 403:
        raise AuthError(f"Authentication failed ({status_code})", status_code=status_code, detail=detail)
    if status_code == 404:
        raise NotFoundError(f"Not found ({status_code})", status_code=status_code, detail=detail)
    if status_code == 422:
        raise ValidationError(f"Validation error ({status_code})", status_code=status_code, detail=detail)
    if status_code == 429:
        raise RateLimitError(detail=detail)
    if status_code >= 500:
        raise ServerError(f"Server error ({status_code})", status_code=status_code, detail=detail)
    raise ModelionnError(f"HTTP error ({status_code})", status_code=status_code, detail=detail)
