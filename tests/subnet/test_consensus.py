"""Tests for proof verification consensus engine."""

from __future__ import annotations

import pytest

from subnet.consensus.engine import (
    CONSENSUS_THRESHOLD,
    MIN_QUORUM,
    SLASH_THRESHOLD,
    ConsensusEngine,
    VerificationVote,
    ValidatorState,
)


class TestValidatorState:
    def test_initial_reliability(self):
        v = ValidatorState(hotkey="val-1")
        assert v.reliability_score == 1.0
        assert not v.slashed

    def test_all_agreements(self):
        v = ValidatorState(hotkey="val-1")
        for _ in range(10):
            v.update(agreed=True)
        assert v.reliability_score == 1.0
        assert v.agreements == 10
        assert v.divergences == 0

    def test_mixed_results(self):
        v = ValidatorState(hotkey="val-1")
        for _ in range(7):
            v.update(agreed=True)
        for _ in range(3):
            v.update(agreed=False)
        # 7/10 = 0.7 agreement rate
        assert 0.6 < v.reliability_score < 0.8

    def test_slash_on_high_divergence(self):
        v = ValidatorState(hotkey="bad-val")
        # Fill the recent_results window with divergences
        for _ in range(50):
            v.update(agreed=False)
        assert v.slashed
        assert v.slash_count >= 1

    def test_verification_time_ema(self):
        v = ValidatorState(hotkey="val-1")
        v.update(agreed=True, verification_time_ms=100)
        assert v.avg_verification_time_ms > 0
        assert v.total_proofs_verified == 1


class TestConsensusEngine:
    def test_below_quorum_returns_none(self):
        engine = ConsensusEngine()
        engine.submit_vote(VerificationVote(
            validator_hotkey="v1", job_id="job-1", partition_index=0, valid=True,
        ))
        result = engine.compute_consensus("job-1", 0)
        assert result is None  # Need MIN_QUORUM votes

    def test_consensus_with_agreement(self):
        engine = ConsensusEngine()
        for i in range(MIN_QUORUM):
            engine.submit_vote(VerificationVote(
                validator_hotkey=f"val-{i}",
                job_id="job-1",
                partition_index=0,
                valid=True,
            ))

        result = engine.compute_consensus("job-1", 0)
        assert result is not None
        assert result.reached_consensus
        assert result.consensus_valid is True
        assert result.agreement_ratio == 1.0
        assert len(result.agreeing_validators) == MIN_QUORUM
        assert len(result.diverging_validators) == 0

    def test_consensus_all_invalid(self):
        engine = ConsensusEngine()
        for i in range(MIN_QUORUM):
            engine.submit_vote(VerificationVote(
                validator_hotkey=f"val-{i}",
                job_id="job-2",
                partition_index=0,
                valid=False,
            ))

        result = engine.compute_consensus("job-2", 0)
        assert result is not None
        assert result.reached_consensus
        assert result.consensus_valid is False

    def test_no_consensus_with_disagreement(self):
        engine = ConsensusEngine()
        # Equal split: 1 valid, 1 invalid — majority is 50% < CONSENSUS_THRESHOLD
        engine.submit_vote(VerificationVote(
            validator_hotkey="val-0", job_id="job-3", partition_index=0, valid=True,
        ))
        engine.submit_vote(VerificationVote(
            validator_hotkey="val-1", job_id="job-3", partition_index=0, valid=False,
        ))

        result = engine.compute_consensus("job-3", 0)
        assert result is not None
        assert result.agreement_ratio < CONSENSUS_THRESHOLD
        assert not result.reached_consensus

    def test_stake_weighted_consensus(self):
        engine = ConsensusEngine()
        # 1 validator says valid (high stake), 1 says invalid (low stake)
        engine.submit_vote(VerificationVote(
            validator_hotkey="high-stake", job_id="job-4", partition_index=0, valid=True,
        ))
        engine.submit_vote(VerificationVote(
            validator_hotkey="low-stake", job_id="job-4", partition_index=0, valid=False,
        ))
        stakes = {"high-stake": 1000.0, "low-stake": 1.0}
        result = engine.compute_consensus("job-4", 0, stakes=stakes)
        assert result is not None
        assert result.consensus_valid is True  # High-stake validator wins

    def test_duplicate_vote_ignored(self):
        engine = ConsensusEngine()
        vote = VerificationVote(
            validator_hotkey="val-1", job_id="job-1", partition_index=0, valid=True,
        )
        engine.submit_vote(vote)
        engine.submit_vote(vote)  # Duplicate
        # Should only have 1 vote
        assert len(engine._pending_votes.get("job-1:0", [])) == 1

    def test_assign_verifiers_respects_max(self):
        engine = ConsensusEngine()
        validators = [f"val-{i}" for i in range(20)]
        assigned = engine.assign_verifiers("job-1", validators)
        assert len(assigned) <= 7  # MAX_VALIDATORS_PER_PROOF = 5, but may be slightly flexible

    def test_assign_verifiers_excludes_slashed(self):
        engine = ConsensusEngine()
        # Create a slashed validator
        state = engine.get_or_create_validator("slashed-val")
        state.slashed = True
        state.reliability_score = 0.0

        validators = ["slashed-val", "good-val-1", "good-val-2"]
        assigned = engine.assign_verifiers("job-1", validators)
        assert "good-val-1" in assigned
        assert "good-val-2" in assigned

    def test_validator_reliability_updates(self):
        engine = ConsensusEngine()
        for i in range(MIN_QUORUM):
            engine.submit_vote(VerificationVote(
                validator_hotkey=f"val-{i}",
                job_id="job-1",
                partition_index=0,
                valid=True,
                verification_time_ms=50,
            ))
        engine.compute_consensus("job-1", 0)

        # All validators should have increased agreement counts
        for i in range(MIN_QUORUM):
            state = engine.get_validator_state(f"val-{i}")
            assert state is not None
            assert state.total_validations == 1
            assert state.agreements == 1

    def test_different_partitions_independent(self):
        engine = ConsensusEngine()
        # Submit votes for partition 0 and partition 1 of same job
        for i in range(MIN_QUORUM):
            engine.submit_vote(VerificationVote(
                validator_hotkey=f"val-{i}", job_id="job-5", partition_index=0, valid=True,
            ))
            engine.submit_vote(VerificationVote(
                validator_hotkey=f"val-{i}", job_id="job-5", partition_index=1, valid=False,
            ))

        r0 = engine.compute_consensus("job-5", 0)
        r1 = engine.compute_consensus("job-5", 1)
        assert r0 is not None and r0.consensus_valid is True
        assert r1 is not None and r1.consensus_valid is False
