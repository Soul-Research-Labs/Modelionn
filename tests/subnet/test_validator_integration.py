"""Integration tests for ValidatorNeuron — commit-reveal and consensus verification."""

from __future__ import annotations

import hashlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Mock bittensor before importing validator module
if "bittensor" not in sys.modules:
    _bt = MagicMock()
    _bt.Synapse = type("Synapse", (), {"__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()] and None})
    _bt.config = MagicMock()
    _bt.dendrite = MagicMock()
    sys.modules["bittensor"] = _bt

from subnet.neurons.validator import ProverInfo, ValidatorNeuron
from subnet.consensus.engine import VerificationVote


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.netuid = 1
    config.neuron.moving_average_alpha = 0.1
    config.neuron.speed_baseline_ms = 60000
    config.neuron.throughput_baseline = 10
    config.neuron.epoch_length = 1
    return config


@pytest.fixture
def validator(mock_config, monkeypatch):
    """Create a ValidatorNeuron with mocked bittensor dependencies."""
    monkeypatch.setattr("subnet.base.neuron.BaseNeuron.__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.load", lambda self: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.save", lambda self, *a, **kw: None)

    v = ValidatorNeuron.__new__(ValidatorNeuron)
    v.config = mock_config
    v.wallet = MagicMock()
    v.dendrite = AsyncMock()
    v.subtensor = MagicMock()
    v.metagraph = MagicMock()
    v.metagraph.n = MagicMock()
    v.metagraph.n.item = MagicMock(return_value=10)
    v.metagraph.hotkeys = [f"hotkey-{i}" for i in range(10)]
    v.metagraph.axons = [MagicMock() for _ in range(10)]
    v.metagraph.S = np.ones(10) * 100.0

    v.scores = np.zeros(10, dtype=np.float32)
    v.alpha = 0.1
    from subnet.reward.scoring import ProverRewardWeights
    v.reward_weights = ProverRewardWeights()
    v._speed_baseline_ms = 60000
    v._throughput_baseline = 10
    v._provers = {}
    v._pending_jobs = {}
    v._step = 0
    v._MAX_COMPLETED_AGE = 600
    v.PING_INTERVAL_STEPS = 5
    v.WEIGHT_SET_INTERVAL = 100
    v._steps_since_weight_set = 0

    from subnet.consensus.engine import ConsensusEngine
    v._consensus = ConsensusEngine()
    v._commits = {}
    v._COMMIT_EXPIRY_S = 600

    from subnet.reward.anti_sybil import ProofHashDeduplicator
    v._deduplicator = ProofHashDeduplicator()

    v._checkpoint = MagicMock()
    return v


# ── Commit-Reveal Tests ─────────────────────────────────────

class TestCommitReveal:
    def test_commit_accepted(self, validator):
        result = validator.handle_commit("hotkey-0", "my-circuit", "deadbeef")
        assert result["accepted"] is True
        assert result["is_earliest"] is True
        assert result["error"] == ""

    def test_duplicate_commit_rejected(self, validator):
        validator.handle_commit("hotkey-0", "my-circuit", "deadbeef")
        result = validator.handle_commit("hotkey-1", "my-circuit", "deadbeef")
        assert result["accepted"] is False
        assert "Duplicate" in result["error"]

    def test_second_commit_not_earliest(self, validator):
        validator.handle_commit("hotkey-0", "circuit-A", "hash1")
        result = validator.handle_commit("hotkey-1", "circuit-A", "hash2")
        assert result["accepted"] is True
        assert result["is_earliest"] is False

    def test_reveal_matches_commit(self, validator):
        name = "test-circuit"
        artifact_hash = "abc123"
        nonce = "my-nonce"
        commit_hash = hashlib.sha256(f"{name}{artifact_hash}{nonce}".encode()).hexdigest()

        validator.handle_commit("hotkey-0", name, commit_hash)
        result = validator.handle_reveal("hotkey-0", name, artifact_hash, nonce)
        assert result["accepted"] is True
        assert result["is_earliest"] is True

    def test_reveal_wrong_nonce_rejected(self, validator):
        name = "test-circuit"
        artifact_hash = "abc123"
        nonce = "my-nonce"
        commit_hash = hashlib.sha256(f"{name}{artifact_hash}{nonce}".encode()).hexdigest()

        validator.handle_commit("hotkey-0", name, commit_hash)
        result = validator.handle_reveal("hotkey-0", name, artifact_hash, "wrong-nonce")
        assert result["accepted"] is False
        assert "No matching commit" in result["error"]

    def test_reveal_wrong_hotkey_rejected(self, validator):
        name = "test-circuit"
        artifact_hash = "abc123"
        nonce = "my-nonce"
        commit_hash = hashlib.sha256(f"{name}{artifact_hash}{nonce}".encode()).hexdigest()

        validator.handle_commit("hotkey-0", name, commit_hash)
        result = validator.handle_reveal("hotkey-1", name, artifact_hash, nonce)
        assert result["accepted"] is False
        assert "hotkey mismatch" in result["error"]

    def test_expired_commits_evicted(self, validator):
        validator._COMMIT_EXPIRY_S = 0  # Expire immediately
        validator.handle_commit("hotkey-0", "circuit", "oldhash")
        # Next commit should evict the expired one
        time.sleep(0.01)
        result = validator.handle_commit("hotkey-1", "circuit", "newhash")
        assert result["accepted"] is True
        assert result["is_earliest"] is True  # Old commit was evicted

    def test_reveal_consumes_commit(self, validator):
        name = "test-circuit"
        artifact_hash = "abc123"
        nonce = "my-nonce"
        commit_hash = hashlib.sha256(f"{name}{artifact_hash}{nonce}".encode()).hexdigest()

        validator.handle_commit("hotkey-0", name, commit_hash)
        validator.handle_reveal("hotkey-0", name, artifact_hash, nonce)
        # Commit should be consumed — second reveal fails
        result = validator.handle_reveal("hotkey-0", name, artifact_hash, nonce)
        assert result["accepted"] is False


# ── Consensus-Integrated Verification Tests ─────────────────

class TestConsensusVerification:
    @pytest.mark.asyncio
    async def test_verify_job_with_consensus(self, validator, monkeypatch):
        """Test that _verify_and_finalize_job uses consensus engine."""
        # Patch ProofVerifySynapse to accept kwargs (bittensor mock may not)
        monkeypatch.setattr(
            "subnet.neurons.validator.ProofVerifySynapse",
            lambda **kw: MagicMock(**kw),
        )

        # Set up online provers
        for i in range(4):
            validator._provers[i] = ProverInfo(
                uid=i, hotkey=f"hotkey-{i}", online=True,
                benchmark_score=90.0, gpu_backend="cuda",
            )

        # Create a mock job with one completed partition
        job = {
            "job_id": "test-job-1",
            "circuit_cid": "cid-circuit",
            "proof_system": "groth16",
            "num_partitions": 1,
            "partitions": [],
            "started_at": time.monotonic(),
            "status": "dispatched",
        }

        partition_done = {
            0: {
                "partition_index": 0,
                "prover_uid": 0,
                "result": {
                    "proof_fragment": b"proof-data-abc",
                    "commitment": "cid-proof-fragment",
                    "generation_time_ms": 500,
                },
            },
        }

        # Mock dendrite to return successful verification
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.valid = True
        validator.dendrite.return_value = [mock_response]

        await validator._verify_and_finalize_job("test-job-1", job, partition_done)
        assert job["status"] == "completed"

    @pytest.mark.asyncio
    async def test_verify_job_fails_on_invalid_consensus(self, validator, monkeypatch):
        """Test that job fails when consensus says proof is invalid."""
        monkeypatch.setattr(
            "subnet.neurons.validator.ProofVerifySynapse",
            lambda **kw: MagicMock(**kw),
        )

        for i in range(4):
            validator._provers[i] = ProverInfo(
                uid=i, hotkey=f"hotkey-{i}", online=True,
                benchmark_score=90.0,
            )

        job = {
            "job_id": "test-job-2",
            "circuit_cid": "cid-circuit",
            "proof_system": "groth16",
            "num_partitions": 1,
            "partitions": [],
            "started_at": time.monotonic(),
            "status": "dispatched",
        }

        partition_done = {
            0: {
                "partition_index": 0,
                "prover_uid": 0,
                "result": {
                    "proof_fragment": b"bad-proof-data",
                    "commitment": "cid-bad",
                    "generation_time_ms": 500,
                },
            },
        }

        # Mock dendrite to return failed verification
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.valid = False
        validator.dendrite.return_value = [mock_response]

        await validator._verify_and_finalize_job("test-job-2", job, partition_done)
        assert job["status"] == "failed"

    @pytest.mark.asyncio
    async def test_verify_skips_when_few_provers(self, validator):
        """Test verification is skipped (auto-accept) with < 2 provers."""
        validator._provers[0] = ProverInfo(uid=0, hotkey="hotkey-0", online=True)

        job = {
            "job_id": "test-job-lonely",
            "circuit_cid": "cid",
            "proof_system": "groth16",
            "num_partitions": 1,
            "partitions": [],
            "started_at": time.monotonic(),
            "status": "dispatched",
        }
        partition_done = {
            0: {
                "partition_index": 0,
                "prover_uid": 0,
                "result": {"proof_fragment": b"data", "commitment": "cid"},
            },
        }

        await validator._verify_and_finalize_job("test-job-lonely", job, partition_done)
        assert job["status"] == "completed"

    @pytest.mark.asyncio
    async def test_verify_handles_dendrite_errors(self, validator, monkeypatch):
        """Test verification gracefully handles network errors."""
        monkeypatch.setattr(
            "subnet.neurons.validator.ProofVerifySynapse",
            lambda **kw: MagicMock(**kw),
        )

        for i in range(3):
            validator._provers[i] = ProverInfo(
                uid=i, hotkey=f"hotkey-{i}", online=True,
                benchmark_score=80.0,
            )

        job = {
            "job_id": "test-job-err",
            "circuit_cid": "cid",
            "proof_system": "plonk",
            "num_partitions": 1,
            "partitions": [],
            "started_at": time.monotonic(),
            "status": "dispatched",
        }

        partition_done = {
            0: {
                "partition_index": 0,
                "prover_uid": 0,
                "result": {
                    "proof_fragment": b"data",
                    "commitment": "cid",
                    "generation_time_ms": 100,
                },
            },
        }

        # Mock dendrite to raise exception
        validator.dendrite.side_effect = ConnectionError("Network failure")

        await validator._verify_and_finalize_job("test-job-err", job, partition_done)
        # Job should fail since all verifications errored
        assert job["status"] == "failed"


# ── Scoring Tests ───────────────────────────────────────────

class TestScoringIntegration:
    def test_compute_scores_with_online_provers(self, validator):
        """Test score computation for provers with completed jobs."""
        validator._provers[0] = ProverInfo(
            uid=0, hotkey="hotkey-0", online=True,
            benchmark_score=95.0,
        )
        validator._provers[1] = ProverInfo(
            uid=1, hotkey="hotkey-1", online=True,
            benchmark_score=50.0,
        )

        # Add a completed job
        validator._pending_jobs["job-1"] = {
            "partitions": [
                {"prover_uid": 0, "status": "completed", "result": {"generation_time_ms": 1000}},
                {"prover_uid": 1, "status": "completed", "result": {"generation_time_ms": 5000}},
                {"prover_uid": 0, "status": "completed", "result": {"generation_time_ms": 800}},
            ],
        }

        scores = validator._compute_scores()
        assert len(scores) == 2
        # Prover 0 should score higher (faster, better benchmark)
        score_0 = next(s for s in scores if s.uid == 0)
        score_1 = next(s for s in scores if s.uid == 1)
        assert score_0.correctness == 1.0  # All successful
        assert score_1.correctness == 1.0
        assert score_0.speed > score_1.speed  # Faster

    def test_compute_scores_with_failures(self, validator):
        """Test score computation handles failed partitions."""
        validator._provers[0] = ProverInfo(uid=0, hotkey="hotkey-0", online=True)
        validator._pending_jobs["job-1"] = {
            "partitions": [
                {"prover_uid": 0, "status": "completed", "result": {"generation_time_ms": 1000}},
                {"prover_uid": 0, "status": "failed", "result": None},
            ],
        }

        scores = validator._compute_scores()
        assert len(scores) == 1
        assert scores[0].correctness == pytest.approx(0.5)  # 1/2 successful

    def test_compute_scores_offline_prover_excluded(self, validator):
        """Test that offline provers are excluded from scoring."""
        validator._provers[0] = ProverInfo(uid=0, hotkey="hotkey-0", online=False)
        scores = validator._compute_scores()
        assert len(scores) == 0
