"""HTTP metrics middleware — counts requests/responses and records latency."""

from __future__ import annotations

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from registry.api.routes.metrics import (
    inc_counter,
    observe_histogram,
    set_gauge,
)

_REQUESTS_TOTAL = "modelionn_http_requests_total"
_REQUEST_LATENCY = "modelionn_http_request_duration_seconds"
_REQUESTS_IN_FLIGHT = "modelionn_http_requests_in_flight"

_in_flight = 0
_in_flight_lock = threading.Lock()


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count, latency, and in-flight gauge for every HTTP call."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        global _in_flight
        with _in_flight_lock:
            _in_flight += 1
            set_gauge(_REQUESTS_IN_FLIGHT, _in_flight)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            with _in_flight_lock:
                _in_flight -= 1
                set_gauge(_REQUESTS_IN_FLIGHT, _in_flight)

        elapsed = time.perf_counter() - start
        inc_counter(_REQUESTS_TOTAL)
        observe_histogram(_REQUEST_LATENCY, elapsed)
        return response
