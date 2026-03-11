"""Tests for subnet reward scoring and anti-Sybil mechanisms."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from subnet.reward.scoring import ProverRewardWeights, ProverScore, compute_prover_rewards
from subnet.reward.anti_sybil import StakeGate, RateLimiter, GpuBenchmarkGate, ProofHashDeduplicator


# ── Scoring ──────────────────────────────────────────────────

class TestProverScore:
    def test_default_weights_total(self):
        score = ProverScore(uid=0, correctness=1.0, speed=1.0, throughput=1.0, reliability=1.0, efficiency=1.0)
        # Sum of default weights = 0.35 + 0.30 + 0.20 + 0.10 + 0.05 = 1.0
        assert abs(score.total() - 1.0) < 1e-6

    def test_zero_scores(self):
        score = ProverScore(uid=0)
        assert score.total() == 0.0

    def test_custom_weights(self):
        w = ProverRewardWeights(correctness=1.0, speed=0, throughput=0, reliability=0, efficiency=0)
        score = ProverScore(uid=0, correctness=0.5)
        assert abs(score.total(w) - 0.5) < 1e-6

    def test_negative_clamps_to_zero(self):
        # Negative factors can't produce negative total because of max(0, ...)
        w = ProverRewardWeights(correctness=1.0, speed=-10.0, throughput=0, reliability=0, efficiency=0)
        score = ProverScore(uid=0, correctness=0.1, speed=1.0)
        assert score.total(w) == 0.0


class TestComputeProverRewards:
    def test_single_prover(self):
        scores = [ProverScore(uid=0, correctness=1.0, speed=0.5)]
        rewards = compute_prover_rewards(scores)
        assert len(rewards) == 1
        assert abs(rewards[0] - 1.0) < 1e-6  # single prover gets all reward

    def test_two_equal_provers(self):
        s1 = ProverScore(uid=0, correctness=0.8, speed=0.8)
        s2 = ProverScore(uid=1, correctness=0.8, speed=0.8)
        rewards = compute_prover_rewards([s1, s2])
        assert abs(rewards[0] - rewards[1]) < 1e-6
        assert abs(sum(rewards) - 1.0) < 1e-6

    def test_all_zero_scores(self):
        scores = [ProverScore(uid=i) for i in range(3)]
        rewards = compute_prover_rewards(scores)
        assert all(r == 0.0 for r in rewards)

    def test_better_prover_higher_reward(self):
        good = ProverScore(uid=0, correctness=1.0, speed=1.0, throughput=1.0, reliability=1.0, efficiency=1.0)
        bad = ProverScore(uid=1, correctness=0.1, speed=0.1)
        rewards = compute_prover_rewards([good, bad])
        assert rewards[0] > rewards[1]


# ── Anti-Sybil: StakeGate ───────────────────────────────────

class TestStakeGate:
    def test_above_threshold_passes(self):
        gate = StakeGate(min_stake=100.0)
        assert gate.check(150.0, "5FTest") is True

    def test_below_threshold_rejected(self):
        gate = StakeGate(min_stake=100.0)
        assert gate.check(50.0, "5FTest") is False

    def test_exact_threshold_passes(self):
        gate = StakeGate(min_stake=100.0)
        assert gate.check(100.0, "5FTest") is True


# ── Anti-Sybil: RateLimiter ─────────────────────────────────

class TestRateLimiter:
    def test_within_limit(self):
        rl = RateLimiter(max_per_epoch=3, epoch_seconds=60)
        assert rl.allow("hk1") is True
        assert rl.allow("hk1") is True
        assert rl.allow("hk1") is True

    def test_exceeds_limit(self):
        rl = RateLimiter(max_per_epoch=2, epoch_seconds=60)
        assert rl.allow("hk1") is True
        assert rl.allow("hk1") is True
        assert rl.allow("hk1") is False

    def test_different_hotkeys_independent(self):
        rl = RateLimiter(max_per_epoch=1, epoch_seconds=60)
        assert rl.allow("hk1") is True
        assert rl.allow("hk2") is True
        assert rl.allow("hk1") is False

    def test_expired_window_resets(self):
        rl = RateLimiter(max_per_epoch=1, epoch_seconds=1)
        assert rl.allow("hk1") is True
        assert rl.allow("hk1") is False
        # Fast-forward past the epoch
        rl._counts["hk1"] = [time.time() - 2]
        assert rl.allow("hk1") is True


# ── Anti-Sybil: GpuBenchmarkGate ────────────────────────────

class TestGpuBenchmarkGate:
    def test_above_minimum(self):
        gate = GpuBenchmarkGate(min_benchmark_score=5000.0)
        assert gate.check(9500.0, "5FTest") is True

    def test_below_minimum(self):
        gate = GpuBenchmarkGate(min_benchmark_score=5000.0)
        assert gate.check(100.0, "5FTest") is False


# ── Anti-Sybil: ProofHashDeduplicator ───────────────────────

class TestProofHashDeduplicator:
    def test_unique_proof(self):
        d = ProofHashDeduplicator()
        assert d.check_and_record("hash1", "job1", 0) is True
        assert d.check_and_record("hash2", "job1", 1) is True

    def test_duplicate_different_key(self):
        d = ProofHashDeduplicator()
        assert d.check_and_record("hash1", "job1", 0) is True
        # Same hash from different job — duplicate
        assert d.check_and_record("hash1", "job2", 0) is False

    def test_same_hash_same_key_allowed(self):
        d = ProofHashDeduplicator()
        assert d.check_and_record("hash1", "job1", 0) is True
        # Re-recording for the same job+partition is not a duplicate
        assert d.check_and_record("hash1", "job1", 0) is True

    def test_eviction_on_max_history(self):
        d = ProofHashDeduplicator(max_history=4)
        for i in range(4):
            assert d.check_and_record(f"h{i}", "j", i) is True
        # Next insertion triggers eviction of first entries
        assert d.check_and_record("h_new", "j", 99) is True
        assert len(d._proof_hashes) <= 4
