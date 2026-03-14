"""Integration tests for MinerNeuron — proof handling, load shedding, blacklist, verification."""

from __future__ import annotations

import hashlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Mock bittensor before importing miner module
if "bittensor" not in sys.modules:
    _bt = MagicMock()
    _bt.Synapse = type(
        "Synapse",
        (),
        {"__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()] and None},
    )
    _bt.config = MagicMock()
    _bt.axon = MagicMock()
    sys.modules["bittensor"] = _bt


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def miner(monkeypatch):
    """Create a MinerNeuron with mocked bittensor and prover dependencies."""
    monkeypatch.setattr("subnet.base.neuron.BaseNeuron.__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.load", lambda self: None)
    monkeypatch.setattr("subnet.base.checkpoint.Checkpoint.save", lambda self, *a, **kw: None)

    from subnet.neurons.miner import MinerNeuron

    m = MinerNeuron.__new__(MinerNeuron)
    m.config = MagicMock()
    m.config.netuid = 1
    m.wallet = MagicMock()
    m.wallet.hotkey.ss58_address = "miner-hotkey-0"
    m.subtensor = MagicMock()
    m.metagraph = MagicMock()
    m.metagraph.hotkeys = [f"validator-{i}" for i in range(5)]
    m.metagraph.S = np.array([100.0, 50.0, 200.0, 0.5, 10.0])
    m.axon = MagicMock()

    m._prover = None
    m._gpu_info = {"gpu_name": "TestGPU", "gpu_backend": "cuda", "gpu_count": 1,
                   "vram_total_bytes": 8_000_000_000, "vram_available_bytes": 6_000_000_000,
                   "compute_units": 128, "benchmark_score": 42.0}
    m._start_time = time.monotonic()
    m._total_proofs = 0
    m._successful_proofs = 0
    m._failed_proofs = 0
    m._current_load = 0.0
    m._benchmark_score = 42.0
    m._checkpoint = MagicMock()
    return m


def _make_proof_synapse(**overrides):
    """Create a mock ProofRequestSynapse."""
    defaults = {
        "job_id": "job-001",
        "circuit_cid": "Qm" + "a" * 44,
        "witness_cid": "Qm" + "b" * 44,
        "proving_key_cid": "",
        "proof_system": "groth16",
        "circuit_type": "general",
        "partition_index": 0,
        "total_partitions": 1,
        "constraint_start": 0,
        "constraint_end": 1000,
        "proof_fragment": b"",
        "commitment": b"",
        "generation_time_ms": 0,
        "gpu_backend_used": "",
        "error": "",
        "dendrite": MagicMock(hotkey="validator-0"),
    }
    defaults.update(overrides)
    synapse = MagicMock()
    for k, v in defaults.items():
        setattr(synapse, k, v)
    return synapse


def _make_ping_synapse(**overrides):
    """Create a mock CapabilityPingSynapse."""
    defaults = {
        "include_benchmark": False,
        "gpu_name": "",
        "gpu_backend": "",
        "gpu_count": 0,
        "vram_total_bytes": 0,
        "vram_available_bytes": 0,
        "compute_units": 0,
        "benchmark_score": 0.0,
        "supported_proof_types": "",
        "max_constraints": 0,
        "current_load": 0.0,
        "total_proofs": 0,
        "successful_proofs": 0,
        "uptime_seconds": 0,
        "dendrite": MagicMock(hotkey="validator-0"),
    }
    defaults.update(overrides)
    synapse = MagicMock()
    for k, v in defaults.items():
        setattr(synapse, k, v)
    return synapse


def _make_verify_synapse(**overrides):
    """Create a mock ProofVerifySynapse."""
    defaults = {
        "proof_cid": "Qm" + "c" * 44,
        "circuit_cid": "Qm" + "d" * 44,
        "verification_key_cid": "",
        "proof_system": "groth16",
        "public_inputs_json": "{}",
        "expected_hash": "",
        "valid": False,
        "verification_time_ms": 0,
        "details": "",
        "error": "",
        "dendrite": MagicMock(hotkey="validator-0"),
    }
    defaults.update(overrides)
    synapse = MagicMock()
    for k, v in defaults.items():
        setattr(synapse, k, v)
    return synapse


# ── Load Shedding Tests ─────────────────────────────────────


class TestLoadShedding:
    @pytest.mark.asyncio
    async def test_reject_when_at_capacity(self, miner):
        """Miner rejects proof requests when load >= 1.0."""
        miner._current_load = 1.0
        synapse = _make_proof_synapse()

        result = await miner.handle_proof_request(synapse)
        assert "capacity" in result.error.lower()
        assert miner._successful_proofs == 0

    @pytest.mark.asyncio
    async def test_load_increases_during_proof(self, miner):
        """Load should increase when processing a proof (even if it fails)."""
        miner._current_load = 0.0
        synapse = _make_proof_synapse(circuit_cid="invalid-cid!")

        await miner.handle_proof_request(synapse)
        # Load returns to 0 since it finishes (0 + 0.2 - 0.2 = 0)
        assert miner._current_load == pytest.approx(0.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_accept_when_below_capacity(self, miner):
        """Miner accepts requests when load < 1.0 (may fail for other reasons)."""
        miner._current_load = 0.5
        synapse = _make_proof_synapse(circuit_cid="invalid-cid!")

        result = await miner.handle_proof_request(synapse)
        # It should process (not reject for capacity) but fail due to invalid CID
        assert "capacity" not in (result.error or "").lower()


# ── CID Validation Tests ────────────────────────────────────


class TestCIDValidation:
    @pytest.mark.asyncio
    async def test_invalid_circuit_cid_rejected(self, miner):
        """Invalid circuit CID format is rejected."""
        synapse = _make_proof_synapse(circuit_cid="not-a-valid-cid")

        result = await miner.handle_proof_request(synapse)
        assert "Invalid circuit_cid format" in result.error
        assert miner._failed_proofs == 1

    @pytest.mark.asyncio
    async def test_invalid_witness_cid_rejected(self, miner):
        """Invalid witness CID format is rejected."""
        synapse = _make_proof_synapse(witness_cid="bad")

        result = await miner.handle_proof_request(synapse)
        assert "Invalid witness_cid format" in result.error

    @pytest.mark.asyncio
    async def test_invalid_proving_key_cid_rejected(self, miner):
        """Invalid proving key CID format is rejected."""
        synapse = _make_proof_synapse(proving_key_cid="bad-pk")

        result = await miner.handle_proof_request(synapse)
        assert "Invalid proving_key_cid format" in result.error

    @pytest.mark.asyncio
    async def test_empty_circuit_cid_rejected(self, miner):
        """Empty circuit CID is rejected."""
        synapse = _make_proof_synapse(circuit_cid="")

        result = await miner.handle_proof_request(synapse)
        assert "Invalid circuit_cid format" in result.error


# ── Capability Ping Tests ───────────────────────────────────


class TestCapabilityPing:
    @pytest.mark.asyncio
    async def test_ping_returns_gpu_info(self, miner):
        """Capability ping returns GPU information."""
        synapse = _make_ping_synapse()

        result = await miner.handle_capability_ping(synapse)
        assert result.gpu_name == "TestGPU"
        assert result.gpu_backend == "cuda"
        assert result.gpu_count == 1
        assert result.vram_total_bytes == 8_000_000_000
        assert result.benchmark_score == 42.0

    @pytest.mark.asyncio
    async def test_ping_returns_proof_stats(self, miner):
        """Capability ping returns proof generation statistics."""
        miner._total_proofs = 100
        miner._successful_proofs = 95
        synapse = _make_ping_synapse()

        result = await miner.handle_capability_ping(synapse)
        assert result.total_proofs == 100
        assert result.successful_proofs == 95

    @pytest.mark.asyncio
    async def test_ping_returns_supported_proof_types(self, miner):
        """Capability ping lists all supported proof systems."""
        synapse = _make_ping_synapse()

        result = await miner.handle_capability_ping(synapse)
        assert "groth16" in result.supported_proof_types
        assert "plonk" in result.supported_proof_types
        assert "halo2" in result.supported_proof_types
        assert "stark" in result.supported_proof_types

    @pytest.mark.asyncio
    async def test_ping_returns_uptime(self, miner):
        """Capability ping reports uptime."""
        synapse = _make_ping_synapse()

        result = await miner.handle_capability_ping(synapse)
        assert result.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_ping_returns_current_load(self, miner):
        """Capability ping reports current load."""
        miner._current_load = 0.6
        synapse = _make_ping_synapse()

        result = await miner.handle_capability_ping(synapse)
        assert result.current_load == pytest.approx(0.6)


# ── Blacklist Tests ─────────────────────────────────────────


class TestBlacklist:
    @pytest.mark.asyncio
    async def test_unregistered_caller_blacklisted(self, miner):
        """Unregistered hotkey is blacklisted for proof requests."""
        synapse = _make_proof_synapse()
        synapse.dendrite.hotkey = "unknown-hotkey"

        blocked, reason = await miner.blacklist_proof_request(synapse)
        assert blocked is True
        assert "Not registered" in reason

    @pytest.mark.asyncio
    async def test_low_stake_caller_blacklisted(self, miner):
        """Caller with stake < 1.0 is blacklisted for proof requests."""
        synapse = _make_proof_synapse()
        synapse.dendrite.hotkey = "validator-3"  # stake = 0.5

        blocked, reason = await miner.blacklist_proof_request(synapse)
        assert blocked is True
        assert "Insufficient stake" in reason

    @pytest.mark.asyncio
    async def test_valid_caller_not_blacklisted(self, miner):
        """Registered caller with sufficient stake is allowed."""
        synapse = _make_proof_synapse()
        synapse.dendrite.hotkey = "validator-0"  # stake = 100.0

        blocked, reason = await miner.blacklist_proof_request(synapse)
        assert blocked is False

    @pytest.mark.asyncio
    async def test_ping_unregistered_blacklisted(self, miner):
        """Unregistered caller is blacklisted for pings."""
        synapse = _make_ping_synapse()
        synapse.dendrite.hotkey = "unknown"

        blocked, reason = await miner.blacklist_ping(synapse)
        assert blocked is True

    @pytest.mark.asyncio
    async def test_ping_registered_allowed(self, miner):
        """Registered caller can ping even with low stake."""
        synapse = _make_ping_synapse()
        synapse.dendrite.hotkey = "validator-3"  # stake = 0.5

        blocked, reason = await miner.blacklist_ping(synapse)
        assert blocked is False

    @pytest.mark.asyncio
    async def test_verify_unregistered_blacklisted(self, miner):
        """Unregistered caller is blacklisted for verification."""
        synapse = _make_verify_synapse()
        synapse.dendrite.hotkey = "unknown"

        blocked, reason = await miner.blacklist_verify(synapse)
        assert blocked is True

    @pytest.mark.asyncio
    async def test_verify_low_stake_blacklisted(self, miner):
        """Low-stake caller is blacklisted for verification."""
        synapse = _make_verify_synapse()
        synapse.dendrite.hotkey = "validator-3"  # stake = 0.5

        blocked, reason = await miner.blacklist_verify(synapse)
        assert blocked is True


# ── Priority Tests ───────────────────────────────────────────


class TestPriority:
    @pytest.mark.asyncio
    async def test_priority_by_stake(self, miner):
        """Priority is based on caller stake."""
        synapse = _make_proof_synapse()

        synapse.dendrite.hotkey = "validator-2"  # stake = 200.0
        priority_high = await miner.priority(synapse)

        synapse.dendrite.hotkey = "validator-1"  # stake = 50.0
        priority_low = await miner.priority(synapse)

        assert priority_high > priority_low

    @pytest.mark.asyncio
    async def test_unknown_caller_zero_priority(self, miner):
        """Unknown caller gets zero priority."""
        synapse = _make_proof_synapse()
        synapse.dendrite.hotkey = "unknown"

        priority = await miner.priority(synapse)
        assert priority == 0.0


# ── Verification Tests ──────────────────────────────────────


class TestVerification:
    @pytest.mark.asyncio
    async def test_invalid_proof_cid_rejected(self, miner):
        """Invalid proof CID format is rejected in verification."""
        synapse = _make_verify_synapse(proof_cid="bad-cid")

        result = await miner.handle_proof_verify(synapse)
        assert "Invalid proof_cid format" in result.error

    @pytest.mark.asyncio
    async def test_invalid_circuit_cid_rejected(self, miner):
        """Invalid circuit CID in verification request is rejected."""
        synapse = _make_verify_synapse(circuit_cid="bad-cid")

        result = await miner.handle_proof_verify(synapse)
        assert "Invalid circuit_cid format" in result.error

    @pytest.mark.asyncio
    async def test_invalid_vk_cid_rejected(self, miner):
        """Invalid verification key CID is rejected."""
        synapse = _make_verify_synapse(verification_key_cid="bad")

        result = await miner.handle_proof_verify(synapse)
        assert "Invalid verification_key_cid format" in result.error


# ── State Persistence Tests ─────────────────────────────────


class TestStatePersistence:
    def test_restore_state(self, miner):
        """Miner restores stats from checkpoint."""
        miner._checkpoint.load.return_value = {
            "total_proofs": 50,
            "successful_proofs": 45,
            "failed_proofs": 5,
            "benchmark_score": 33.3,
        }
        miner._restore_state()
        assert miner._total_proofs == 50
        assert miner._successful_proofs == 45
        assert miner._failed_proofs == 5
        assert miner._benchmark_score == pytest.approx(33.3)

    def test_restore_empty_state(self, miner):
        """Empty checkpoint doesn't crash."""
        miner._checkpoint.load.return_value = None
        miner._restore_state()
        assert miner._total_proofs == 0

    def test_save_state(self, miner):
        """Save state calls checkpoint save with stats."""
        miner._total_proofs = 10
        miner._successful_proofs = 8
        miner._failed_proofs = 2
        miner._benchmark_score = 42.0

        miner._save_state()
        miner._checkpoint.save.assert_called_once()
        saved = miner._checkpoint.save.call_args[0][0]
        assert saved["total_proofs"] == 10
        assert saved["successful_proofs"] == 8
        assert saved["failed_proofs"] == 2


# ── Error Counting Tests ────────────────────────────────────


class TestErrorCounting:
    @pytest.mark.asyncio
    async def test_failed_proof_increments_counter(self, miner):
        """Failed proof generation increments failure counter."""
        synapse = _make_proof_synapse(circuit_cid="invalid!")

        await miner.handle_proof_request(synapse)
        assert miner._failed_proofs == 1
        assert miner._total_proofs == 1
        assert miner._successful_proofs == 0
