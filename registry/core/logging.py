"""Structured JSON logging for the ZKML registry.

Uses stdlib logging with a custom JSON formatter so there's no extra dependency.
Request-ID from RequestIDMiddleware is included automatically when available.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from registry.api.middleware.request_id import request_id_ctx


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach request-id if available
        rid = request_id_ctx.get("")
        if rid:
            payload["request_id"] = rid

        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging(*, json_output: bool = True, level: str = "INFO") -> None:
    """Configure root logger. Call once at startup."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s  %(message)s"))
    root.addHandler(handler)

    # Quiet noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
