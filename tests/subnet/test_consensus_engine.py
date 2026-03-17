"""Tests for the multi-validator consensus engine."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from subnet.consensus.engine import (
    ConsensusEngine,
    VerificationVote,
    ValidatorState,
    MIN_QUORUM,
    CONSENSUS_THRESHOLD,
    SLASH_THRESHOLD,
    DIVERGENCE_WINDOW,
    MAX_VALIDATORS_PER_PROOF,
)


@pytest.fixture
def engine():
    return ConsensusEngine()


def _vote(validator: str, job: str = "job1", partition: int = 0,
          valid: bool = True, time_ms: int = 100) -> VerificationVote:
    return VerificationVote(
        validator_hotkey=validator,
        job_id=job,
        partition_index=partition,
        valid=valid,
        verification_time_ms=time_ms,
    )


# ── Vote submission ──────────────────────────────────────────


class TestSubmitVote:
    def test_single_vote(self, engine):
        engine.submit_vote(_vote("v1"))
        assert len(engine._pending_votes["job1:0"]) == 1

    def test_multiple_validators(self, engine):
        engine.submit_vote(_vote("v1"))
        engine.submit_vote(_vote("v2"))
        assert len(engine._pending_votes["job1:0"]) == 2

    def test_duplicate_vote_ignored(self, engine):
        engine.submit_vote(_vote("v1"))
        engine.submit_vote(_vote("v1"))
        assert len(engine._pending_votes["job1:0"]) == 1

    def test_separate_partitions(self, engine):
        engine.submit_vote(_vote("v1", partition=0))
        engine.submit_vote(_vote("v1", partition=1))
        assert len(engine._pending_votes["job1:0"]) == 1
        assert len(engine._pending_votes["job1:1"]) == 1


# ── Consensus computation ────────────────────────────────────


class TestComputeConsensus:
    def test_below_quorum_returns_none(self, engine):
        engine.submit_vote(_vote("v1"))
        result = engine.compute_consensus("job1", 0)
        assert result is None

    def test_quorum_met_consensus_reached(self, engine):
        engine.submit_vote(_vote("v1", valid=True))
        engine.submit_vote(_vote("v2", valid=True))
        result = engine.compute_consensus("job1", 0)
        assert result is not None
        assert result.consensus_valid is True
        assert result.reached_consensus is True
        assert result.agreement_ratio == 1.0
        assert result.quorum_size == 2

    def test_unanimous_invalid(self, engine):
        engine.submit_vote(_vote("v1", valid=False))
        engine.submit_vote(_vote("v2", valid=False))
        result = engine.compute_consensus("job1", 0)
        assert result is not None
        assert result.consensus_valid is False
        assert result.reached_consensus is True
        assert result.agreement_ratio == 1.0

    def test_majority_valid_with_minority_invalid(self, engine):
        engine.submit_vote(_vote("v1", valid=True))
        engine.submit_vote(_vote("v2", valid=True))
        engine.submit_vote(_vote("v3", valid=False))
        result = engine.compute_consensus("job1", 0)
        assert result is not None
        assert result.consensus_valid is True
        assert "v3" in result.diverging_validators
        assert "v1" in result.agreeing_validators
        assert "v2" in result.agreeing_validators

    def test_stake_weighted_consensus(self, engine):
        engine.submit_vote(_vote("v1", valid=True))
        engine.submit_vote(_vote("v2", valid=False))
        # v1 has much higher stake → valid wins
        result = engine.compute_consensus("job1", 0, stakes={"v1": 1000.0, "v2": 1.0})
        assert result is not None
        assert result.consensus_valid is True

    def test_stake_weighted_invalid_wins(self, engine):
        engine.submit_vote(_vote("v1", valid=True))
        engine.submit_vote(_vote("v2", valid=False))
        # v2 has much higher stake → invalid wins
        result = engine.compute_consensus("job1", 0, stakes={"v1": 1.0, "v2": 1000.0})
        assert result is not None
        assert result.consensus_valid is False

    def test_votes_cleared_after_consensus(self, engine):
        engine.submit_vote(_vote("v1"))
        engine.submit_vote(_vote("v2"))
        engine.compute_consensus("job1", 0)
        assert "job1:0" not in engine._pending_votes

    def test_avg_verification_time(self, engine):
        engine.submit_vote(_vote("v1", time_ms=100))
        engine.submit_vote(_vote("v2", time_ms=200))
        result = engine.compute_consensus("job1", 0)
        assert result.avg_verification_time_ms == 150.0


# ── Validator reliability ────────────────────────────────────


class TestValidatorReliability:
    def test_initial_state(self, engine):
        state = engine.get_or_create_validator("v1")
        assert state.reliability_score == 1.0
        assert state.slashed is False
        assert state.total_validations == 0

    def test_agreement_maintains_high_reliability(self, engine):
        state = engine.get_or_create_validator("v1")
        for _ in range(10):
            state.update(agreed=True, verification_time_ms=50)
        assert state.reliability_score > 0.9

    def test_divergence_lowers_reliability(self, engine):
        state = engine.get_or_create_validator("v1")
        for _ in range(10):
            state.update(agreed=False)
        assert state.reliability_score < 0.5

    def test_slashing_triggered_after_divergence_window(self, engine):
        state = engine.get_or_create_validator("v1")
        # Fill the divergence window with all disagreements
        for _ in range(DIVERGENCE_WINDOW):
            state.update(agreed=False)
        assert state.slashed is True
        assert state.slash_count >= 1

    def test_partial_divergence_no_slash(self, engine):
        state = engine.get_or_create_validator("v1")
        # 80% agreement should NOT trigger slash (< SLASH_THRESHOLD = 20% divergence)
        for i in range(DIVERGENCE_WINDOW):
            state.update(agreed=(i % 5 != 0))  # 80% agree
        assert state.slashed is False

    def test_ema_verification_time(self, engine):
        state = engine.get_or_create_validator("v1")
        state.update(agreed=True, verification_time_ms=100)
        state.update(agreed=True, verification_time_ms=200)
        # EMA: 0.1 * 200 + 0.9 * (0.1 * 100 + 0.9 * 0) = 20 + 9 = 29
        assert state.avg_verification_time_ms > 0


# ── Verifier assignment ──────────────────────────────────────


class TestAssignVerifiers:
    def test_fewer_than_max_returns_all(self, engine):
        validators = ["v1", "v2"]
        selected = engine.assign_verifiers("job1", validators)
        assert set(selected) == set(validators)

    def test_max_verifiers_respected(self, engine):
        validators = [f"v{i}" for i in range(20)]
        selected = engine.assign_verifiers("job1", validators)
        assert len(selected) <= MAX_VALIDATORS_PER_PROOF

    def test_slashed_validators_deprioritized(self, engine):
        # Slash v1
        state = engine.get_or_create_validator("v1")
        state.slashed = True

        # Need more than MAX_VALIDATORS_PER_PROOF to trigger weighted selection
        validators = [f"v{i}" for i in range(10)]
        # Run multiple selections — slashed should be very rare
        all_selected = []
        for i in range(50):
            selected = engine.assign_verifiers(f"job{i}", validators)
            all_selected.extend(selected)
        v1_count = all_selected.count("v1")
        # v1 has weight 0, so should never be selected
        assert v1_count == 0


# ── Slashing and unslashing ──────────────────────────────────


class TestSlashManagement:
    def test_get_slashed_validators(self, engine):
        engine.get_or_create_validator("v1").slashed = True
        engine.get_or_create_validator("v2").slashed = False
        engine.get_or_create_validator("v3").slashed = True
        slashed = engine.get_slashed_validators()
        hotkeys = [v.hotkey for v in slashed]
        assert "v1" in hotkeys
        assert "v3" in hotkeys
        assert "v2" not in hotkeys

    def test_try_unslash_success(self, engine):
        state = engine.get_or_create_validator("v1")
        state.slashed = True
        # Fill window with all agreements to get high reliability
        for _ in range(DIVERGENCE_WINDOW):
            state.update(agreed=True)
        result = engine.try_unslash("v1", min_reliability=0.85)
        assert result is True
        assert state.slashed is False

    def test_try_unslash_insufficient_reliability(self, engine):
        state = engine.get_or_create_validator("v1")
        state.slashed = True
        # Mix of agree/disagree = low reliability
        for i in range(DIVERGENCE_WINDOW):
            state.update(agreed=(i % 2 == 0))
        result = engine.try_unslash("v1", min_reliability=0.85)
        assert result is False
        assert state.slashed is True

    def test_try_unslash_not_slashed(self, engine):
        engine.get_or_create_validator("v1")
        assert engine.try_unslash("v1") is False

    def test_try_unslash_unknown_validator(self, engine):
        assert engine.try_unslash("unknown") is False


# ── Statistics ───────────────────────────────────────────────


class TestGetStats:
    def test_empty_engine(self, engine):
        stats = engine.get_stats()
        assert stats["total_validators"] == 0
        assert stats["active_validators"] == 0
        assert stats["slashed_validators"] == 0
        assert stats["pending_vote_sets"] == 0

    def test_populated_engine(self, engine):
        engine.get_or_create_validator("v1")
        engine.get_or_create_validator("v2").slashed = True
        engine.submit_vote(_vote("v1"))
        stats = engine.get_stats()
        assert stats["total_validators"] == 2
        assert stats["slashed_validators"] == 1
        assert stats["pending_vote_sets"] == 1


# ── Cleanup ──────────────────────────────────────────────────


class TestCleanup:
    def test_evict_stale_validators(self, engine):
        state = engine.get_or_create_validator("v1")
        state.last_active = time.monotonic() - 7200  # 2 hours ago
        engine.get_or_create_validator("v2")  # fresh
        engine.cleanup()
        assert "v1" not in engine._validators
        assert "v2" in engine._validators

    def test_expire_pending_votes(self, engine):
        engine.submit_vote(_vote("v1"))
        # Simulate old timestamp
        engine._vote_timestamps["job1:0"] = time.monotonic() - 1200
        engine.cleanup()
        assert "job1:0" not in engine._pending_votes
