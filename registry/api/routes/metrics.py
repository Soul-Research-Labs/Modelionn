"""Prometheus-compatible metrics — in-memory counters, histograms, and gauges.

Provides a ``/metrics`` endpoint and helper functions used by middleware
to record HTTP request stats, API key usage, and nonce replay events.
"""

from __future__ import annotations

import threading

from fastapi import APIRouter

router = APIRouter()

# ── Counter / gauge names ────────────────────────────────────
API_KEY_REQUESTS = "modelionn_api_key_requests_total"
API_KEY_REJECTIONS = "modelionn_api_key_rejections_total"
NONCE_REPLAYS_BLOCKED = "modelionn_nonce_replays_blocked_total"
PROOFS_GENERATED = "modelionn_proofs_generated_total"
CIRCUITS_UPLOADED = "modelionn_circuits_uploaded_total"
PROVERS_ONLINE = "modelionn_provers_online"

# ── Threadsafe storage ───────────────────────────────────────
_lock = threading.Lock()
_counters: dict[str, float] = {}
_gauges: dict[str, float] = {}
_histogram_sums: dict[str, float] = {}
_histogram_counts: dict[str, int] = {}


def inc_counter(name: str, value: float = 1.0) -> None:
    """Increment a counter (monotonically increasing)."""
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + value


def set_gauge(name: str, value: float) -> None:
    """Set a gauge to an absolute value."""
    with _lock:
        _gauges[name] = value


def observe_histogram(name: str, value: float) -> None:
    """Record a histogram observation (sum + count)."""
    with _lock:
        _histogram_sums[name] = _histogram_sums.get(name, 0.0) + value
        _histogram_counts[name] = _histogram_counts.get(name, 0) + 1


def _format_prometheus() -> str:
    """Render all metrics in Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        for name, val in sorted(_counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {val}")
        for name, val in sorted(_gauges.items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {val}")
        for name in sorted(_histogram_sums):
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{name}_sum {_histogram_sums[name]}")
            lines.append(f"{name}_count {_histogram_counts.get(name, 0)}")
    return "\n".join(lines) + "\n"


@router.get("", include_in_schema=False)
async def prometheus_metrics() -> str:
    """Prometheus scrape endpoint."""
    from starlette.responses import PlainTextResponse
    return PlainTextResponse(_format_prometheus(), media_type="text/plain; charset=utf-8")
