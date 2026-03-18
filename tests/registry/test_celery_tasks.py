"""Tests for Celery task utility functions — proof dispatch helpers, webhook delivery signing,
and circuit breaker logic."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from threading import Lock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# proof_dispatch helpers (these are pure functions, no DB needed)
# ---------------------------------------------------------------------------

class TestBuildCumulativeWeights:
    """Tests for _build_cumulative_weights in proof_dispatch."""

    def test_empty(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        assert _build_cumulative_weights([]) == []

    def test_single_score(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        result = _build_cumulative_weights([10.0])
        assert len(result) == 1
        assert abs(result[0] - 1.0) < 1e-9

    def test_equal_scores(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        result = _build_cumulative_weights([5.0, 5.0, 5.0])
        assert len(result) == 3
        assert abs(result[-1] - 1.0) < 1e-9
        # Each bucket should be ~0.333
        assert abs(result[0] - 1 / 3) < 0.01

    def test_zero_scores_uniform(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        result = _build_cumulative_weights([0.0, 0.0, 0.0])
        assert len(result) == 3
        assert abs(result[-1] - 1.0) < 1e-9
        # Uniform fallback: 1/3, 2/3, 1.0
        assert abs(result[0] - 1 / 3) < 0.01

    def test_negative_scores_clamped(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        result = _build_cumulative_weights([-5.0, 10.0])
        assert len(result) == 2
        # -5 clamped to 0, so all weight goes to second
        assert abs(result[-1] - 1.0) < 1e-9

    def test_monotonically_increasing(self):
        from registry.tasks.proof_dispatch import _build_cumulative_weights

        result = _build_cumulative_weights([1.0, 2.0, 3.0, 4.0])
        for i in range(1, len(result)):
            assert result[i] >= result[i - 1]


class TestPickWeightedIndex:
    """Tests for _pick_weighted_index."""

    def test_empty_weights(self):
        from registry.tasks.proof_dispatch import _pick_weighted_index

        assert _pick_weighted_index(0, []) == 0

    def test_single_weight(self):
        from registry.tasks.proof_dispatch import _pick_weighted_index

        assert _pick_weighted_index(0, [1.0]) == 0

    def test_deterministic(self):
        from registry.tasks.proof_dispatch import _pick_weighted_index

        weights = [0.25, 0.5, 0.75, 1.0]
        # Same index should always return the same result
        a = _pick_weighted_index(42, weights)
        b = _pick_weighted_index(42, weights)
        assert a == b

    def test_valid_range(self):
        from registry.tasks.proof_dispatch import _pick_weighted_index

        weights = [0.2, 0.5, 0.8, 1.0]
        for i in range(100):
            idx = _pick_weighted_index(i, weights)
            assert 0 <= idx < len(weights)


# ---------------------------------------------------------------------------
# webhook_delivery helpers — HMAC signing, circuit breaker
# ---------------------------------------------------------------------------

class TestWebhookHMACSigning:
    """Tests for _sign_payload in webhook_delivery."""

    def test_deterministic_signature(self):
        from registry.tasks.webhook_delivery import _sign_payload

        payload = b'{"event": "proof.completed"}'
        secret = "whsec_abc123"
        sig1 = _sign_payload(payload, secret)
        sig2 = _sign_payload(payload, secret)
        assert sig1 == sig2

    def test_signature_format(self):
        from registry.tasks.webhook_delivery import _sign_payload

        sig = _sign_payload(b"test", "secret")
        # HMAC-SHA256 hex → 64 chars
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_manual_verification(self):
        from registry.tasks.webhook_delivery import _sign_payload

        payload = b'{"test": true}'
        secret = "my_secret_key"
        sig = _sign_payload(payload, secret)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert sig == expected

    def test_different_payloads_differ(self):
        from registry.tasks.webhook_delivery import _sign_payload

        a = _sign_payload(b"payload_a", "secret")
        b = _sign_payload(b"payload_b", "secret")
        assert a != b

    def test_different_secrets_differ(self):
        from registry.tasks.webhook_delivery import _sign_payload

        a = _sign_payload(b"same_payload", "secret_1")
        b = _sign_payload(b"same_payload", "secret_2")
        assert a != b


class TestCircuitBreaker:
    """Tests for in-process circuit breaker logic."""

    @pytest.fixture(autouse=True)
    def _reset_breaker(self):
        from registry.tasks.webhook_delivery import (
            _cb_failures,
            _cb_open_until,
            _cb_lock,
        )

        with _cb_lock:
            _cb_failures.clear()
            _cb_open_until.clear()
        yield
        with _cb_lock:
            _cb_failures.clear()
            _cb_open_until.clear()

    def test_breaker_initially_closed(self):
        from registry.tasks.webhook_delivery import _is_circuit_open

        assert _is_circuit_open(webhook_id=999) is False

    def test_breaker_opens_after_threshold(self):
        from registry.tasks.webhook_delivery import (
            _record_delivery_failure,
            _is_circuit_open,
            _CIRCUIT_FAILURE_THRESHOLD,
        )

        # Record failures up to threshold
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD - 1):
            tripped = _record_delivery_failure(1)
            assert tripped is False

        # One more should trip it
        tripped = _record_delivery_failure(1)
        assert tripped is True
        assert _is_circuit_open(1) is True

    def test_breaker_resets_after_expiry(self):
        from registry.tasks.webhook_delivery import (
            _record_delivery_failure,
            _is_circuit_open,
            _CIRCUIT_FAILURE_THRESHOLD,
            _CIRCUIT_OPEN_SECONDS,
        )

        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(1)

        # Past expiry should auto-close
        future = time.time() + _CIRCUIT_OPEN_SECONDS + 1
        assert _is_circuit_open(1, now=future) is False

    def test_success_resets_failure_count(self):
        from registry.tasks.webhook_delivery import (
            _record_delivery_failure,
            _record_delivery_success,
            _is_circuit_open,
        )

        _record_delivery_failure(1)
        _record_delivery_failure(1)
        _record_delivery_success(1)
        assert _is_circuit_open(1) is False

    def test_per_webhook_isolation(self):
        from registry.tasks.webhook_delivery import (
            _record_delivery_failure,
            _is_circuit_open,
            _CIRCUIT_FAILURE_THRESHOLD,
        )

        # Open breaker for webhook 1
        for _ in range(_CIRCUIT_FAILURE_THRESHOLD):
            _record_delivery_failure(1)

        assert _is_circuit_open(1) is True
        # Webhook 2 should still be closed
        assert _is_circuit_open(2) is False


# ---------------------------------------------------------------------------
# dispatch lock key
# ---------------------------------------------------------------------------

class TestDispatchLockKey:
    def test_format(self):
        from registry.tasks.proof_dispatch import _dispatch_lock_key

        assert _dispatch_lock_key(42) == "dispatch_job_42"
        assert _dispatch_lock_key(1) == "dispatch_job_1"
