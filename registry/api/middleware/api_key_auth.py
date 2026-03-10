"""API key authentication middleware.

Checks for ``Authorization: Bearer mnn_...`` on every request.
If present, validates the key against the database, increments usage counters,
and injects ``x-authenticated-hotkey`` into the request state.

Requests without an API key header pass through (relying on per-route
``verify_publisher`` for auth).
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sqlalchemy import select, update

from registry.core.deps import get_async_session
from registry.models.database import APIKeyRow
from registry.api.routes.metrics import inc_counter, API_KEY_REQUESTS, API_KEY_REJECTIONS

logger = logging.getLogger(__name__)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        auth_header: str = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer mnn_"):
            return await call_next(request)

        raw_key = auth_header.removeprefix("Bearer ").strip()
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        async with get_async_session() as db:
            # Fetch all keys for this hotkey-prefix to do constant-time comparison
            result = await db.execute(
                select(APIKeyRow).where(APIKeyRow.key_hash == key_hash)
            )
            row = result.scalar_one_or_none()

            # Constant-time comparison to prevent timing attacks
            if row is None or not _hmac.compare_digest(key_hash, row.key_hash):
                inc_counter(API_KEY_REJECTIONS)
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)

            if row.requests_today >= row.daily_limit:
                inc_counter(API_KEY_REJECTIONS)
                return JSONResponse({"detail": "Daily API key limit exceeded"}, status_code=429)

            inc_counter(API_KEY_REQUESTS)

            # Increment usage
            await db.execute(
                update(APIKeyRow)
                .where(APIKeyRow.id == row.id)
                .values(
                    requests_today=APIKeyRow.requests_today + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        # Expose authenticated hotkey to downstream route handlers
        request.state.api_key_hotkey = row.hotkey
        return await call_next(request)
