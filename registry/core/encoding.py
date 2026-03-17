"""Shared base64 helpers for registry/core modules.

This module is intentionally registry-scoped. Prover-side Python bindings do not
carry a parallel encoding helper to avoid duplicate implementations.
"""

from __future__ import annotations

import base64

def toBase64(data: bytes | str) -> str:
    """Safe cross-platform base64 encoding."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")

def fromBase64(data: str) -> bytes:
    """Safe cross-platform base64 decoding."""
    return base64.b64decode(data, validate=True)
