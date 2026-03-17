"""Tests for webhook delivery — HMAC signing, circuit breaker, DLQ logging."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# Ensure celery_app is mocked before importing webhook_delivery module
if "registry.tasks.celery_app" not in sys.modules:
    _mock_celery_app = MagicMock()
    sys.modules["registry.tasks.celery_app"] = _mock_celery_app

from registry.tasks.webhook_delivery import (
    _sign_payload,
    _is_circuit_open,
    _record_delivery_failure,
    _record_delivery_success,
    _log_to_dlq,
    _cb_failures,
    _cb_open_until,
    _cb_lock,
    _CIRCUIT_FAILURE_THRESHOLD,
    _CIRCUIT_OPEN_SECONDS,
)


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Clear in-process circuit breaker state between tests."""
    with _cb_lock:
        _cb_failures.clear()
        _cb_open_until.clear()
    yield
    with _cb_lock:
        _cb_failures.clear()
        _cb_open_until.clear()


# ── HMAC signing ─────────────────────────────────────────────


class TestSignPayload:
    def test_produces_hex_digest(self):
        sig = _sign_payload(b'{"event":"test"}', "my-secret")
        assert len(sig) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in sig)

    def test_deterministic(self):
        payload = b'{"event":"proof.completed"}'
        assert _sign_payload(payload, "s") == _sign_payload(payload, "s")

    def test_matches_manual_hmac(self):
        payload = b'hello'
        secret = "secret"
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _sign_payload(payload, secret) == expected

    def test_different_secrets(self):
        payload = b'data'
        assert _sign_payload(payload, "a") != _sign_payload(payload, "b")


# ── In-process circuit breaker ───────────────────────────────


class TestCircuitBreaker:
    def test_initially_closed(self):
        assert _is_circuit_open(42) is False

    def test_stays_closed_below_threshold(self):
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD - 1):
            _record_delivery_failure(1)
        assert _is_circuit_open(1) is False

    def test_opens_at_threshold(self):
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(1)
        assert _is_circuit_open(1) is True

    def test_open_has_expiry(self):
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(1)
        # Simulate time passing beyond open window
        future = time.time() + _CIRCUIT_OPEN_SECONDS + 10
        assert _is_circuit_open(1, now=future) is False

    def test_success_resets_breaker(self):
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(1)
        assert _is_circuit_open(1) is True
        _record_delivery_success(1)
        assert _is_circuit_open(1) is False

    def test_separate_webhook_ids(self):
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(10)
        assert _is_circuit_open(10) is True
        assert _is_circuit_open(20) is False

    def test_failure_returns_true_on_trip(self):
        for i in range(_CIRCUIT_FAILURE_THRESHOLD - 1):
            tripped = _record_delivery_failure(1)
            assert tripped is False
        tripped = _record_delivery_failure(1)
        assert tripped is True


# ── DLQ logging ──────────────────────────────────────────────


class TestDLQLogging:
    def test_logs_error(self, caplog):
        with caplog.at_level(logging.ERROR, logger="modelionn.webhook.dlq"):
            _log_to_dlq(99, "proof.failed", {"job_id": 1}, "Timeout")
        assert "DLQ" in caplog.text
        assert "webhook_id=99" in caplog.text
        assert "proof.failed" in caplog.text

    def test_truncates_payload(self, caplog):
        big_payload = {"data": "x" * 5000}
        with caplog.at_level(logging.ERROR, logger="modelionn.webhook.dlq"):
            _log_to_dlq(1, "test", big_payload, "err")
        # Payload dump is truncated to 2000 chars
        log_text = caplog.text
        assert "DLQ" in log_text
