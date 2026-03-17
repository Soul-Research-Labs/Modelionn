"""Tests for proof dispatch helpers and anti-sybil gates."""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock

import pytest

# Mock celery before any registry.tasks import
if "registry.tasks.celery_app" not in sys.modules:
    sys.modules["registry.tasks.celery_app"] = MagicMock()

# Mock pydantic_settings so registry.core.config can load without the real package
if "pydantic_settings" not in sys.modules:
    _mock_ps = MagicMock()
    _mock_ps.SettingsConfigDict = lambda **kw: {}
    sys.modules["pydantic_settings"] = _mock_ps

from registry.tasks.proof_dispatch import (
    _build_cumulative_weights,
    _pick_weighted_index,
)


# ── Cumulative weight builder ────────────────────────────────


class TestBuildCumulativeWeights:
    def test_empty_list(self):
        assert _build_cumulative_weights([]) == []

    def test_uniform_weights(self):
        weights = _build_cumulative_weights([1.0, 1.0, 1.0])
        assert len(weights) == 3
        assert abs(weights[-1] - 1.0) < 1e-9

    def test_single_weight(self):
        weights = _build_cumulative_weights([5.0])
        assert weights == [1.0]

    def test_monotonically_increasing(self):
        weights = _build_cumulative_weights([3.0, 2.0, 5.0])
        for i in range(1, len(weights)):
            assert weights[i] >= weights[i - 1]

    def test_zero_weights_uniform_fallback(self):
        weights = _build_cumulative_weights([0.0, 0.0, 0.0])
        assert len(weights) == 3
        # When all zeros, falls back to uniform distribution
        assert abs(weights[-1] - 1.0) < 1e-9

    def test_negative_weights_clamped(self):
        weights = _build_cumulative_weights([-1.0, 2.0, 3.0])
        assert len(weights) == 3
        # Negative clamped to 0; only 2+3=5 contribute
        assert abs(weights[0] - 0.0) < 1e-9
        assert abs(weights[-1] - 1.0) < 1e-9


# ── Weighted index picker ────────────────────────────────────


class TestPickWeightedIndex:
    def test_empty_weights(self):
        assert _pick_weighted_index(0, []) == 0

    def test_single_element(self):
        assert _pick_weighted_index(0, [1.0]) == 0

    def test_deterministic(self):
        weights = [0.25, 0.50, 0.75, 1.0]
        idx1 = _pick_weighted_index(42, weights)
        idx2 = _pick_weighted_index(42, weights)
        assert idx1 == idx2

    def test_different_indices_may_differ(self):
        weights = [0.25, 0.50, 0.75, 1.0]
        results = {_pick_weighted_index(i, weights) for i in range(100)}
        # Should pick at least 2 different positions across 100 inputs
        assert len(results) >= 2

    def test_returns_valid_index(self):
        weights = _build_cumulative_weights([10.0, 20.0, 30.0])
        for i in range(50):
            idx = _pick_weighted_index(i, weights)
            assert 0 <= idx < 3


# ── Anti-sybil: BenchmarkVerifier ────────────────────────────


from subnet.reward.anti_sybil import BenchmarkVerifier


class TestBenchmarkVerifier:
    def test_needs_verification_unknown(self):
        bv = BenchmarkVerifier(cache_ttl_s=60)
        assert bv.needs_verification("miner1") is True

    def test_record_pass(self):
        bv = BenchmarkVerifier()
        # claimed=10 proofs/s, actual_time=0.05s → actual_score=20 → 20 >= 10*0.3 → pass
        assert bv.record("miner1", claimed=10.0, actual_time_s=0.05) is True
        assert bv.is_trusted("miner1") is True
        assert bv.needs_verification("miner1") is False

    def test_record_fail(self):
        bv = BenchmarkVerifier()
        # claimed=100, actual_time=10s → actual_score=0.1 → 0.1 < 100*0.3 → fail
        assert bv.record("miner2", claimed=100.0, actual_time_s=10.0) is False
        assert bv.is_trusted("miner2") is False

    def test_cache_expiry(self):
        bv = BenchmarkVerifier(cache_ttl_s=1)
        bv.record("miner1", claimed=1.0, actual_time_s=0.1)
        assert bv.is_trusted("miner1") is True
        # Expire the cache
        bv._cache["miner1"] = (10.0, time.time() - 5, True)
        assert bv.needs_verification("miner1") is True
        assert bv.is_trusted("miner1") is False


# ── Anti-sybil: ProofHashDeduplicator ────────────────────────


from subnet.reward.anti_sybil import ProofHashDeduplicator


class TestProofHashDeduplicator:
    def test_unique_hash(self):
        d = ProofHashDeduplicator()
        assert d.check_and_record("abc123", "job1", 0) is True

    def test_same_hash_same_key(self):
        d = ProofHashDeduplicator()
        d.check_and_record("abc123", "job1", 0)
        # Same hash, same job/partition → allowed
        assert d.check_and_record("abc123", "job1", 0) is True

    def test_duplicate_hash_different_key(self):
        d = ProofHashDeduplicator()
        d.check_and_record("abc123", "job1", 0)
        # Same hash, different partition → duplicate
        assert d.check_and_record("abc123", "job2", 0) is False

    def test_eviction_on_overflow(self):
        d = ProofHashDeduplicator(max_history=10)
        for i in range(15):
            d.check_and_record(f"hash{i}", str(i), 0)
        # Should have evicted some early entries
        assert len(d._proof_hashes) <= 13  # 10 max + some tolerance after eviction


# ── Anti-sybil: RateLimiter ──────────────────────────────────


from subnet.reward.anti_sybil import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter(max_per_epoch=5, epoch_seconds=60)
        for _ in range(5):
            assert rl.allow("miner1") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_per_epoch=3, epoch_seconds=60)
        for _ in range(3):
            rl.allow("miner1")
        assert rl.allow("miner1") is False

    def test_separate_hotkeys(self):
        rl = RateLimiter(max_per_epoch=2, epoch_seconds=60)
        rl.allow("a")
        rl.allow("a")
        assert rl.allow("a") is False
        assert rl.allow("b") is True  # different key still has budget


# ── Anti-sybil: GpuBenchmarkGate ─────────────────────────────


from subnet.reward.anti_sybil import GpuBenchmarkGate


class TestGpuBenchmarkGate:
    def test_above_minimum(self):
        gate = GpuBenchmarkGate(min_benchmark_score=5.0)
        assert gate.check(10.0, "miner1") is True

    def test_below_minimum(self):
        gate = GpuBenchmarkGate(min_benchmark_score=5.0)
        assert gate.check(3.0, "miner1") is False

    def test_exact_minimum(self):
        gate = GpuBenchmarkGate(min_benchmark_score=5.0)
        assert gate.check(5.0, "miner1") is True
