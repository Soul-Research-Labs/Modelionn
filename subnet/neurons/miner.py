"""ZKML Prover Miner — GPU-accelerated ZK proof generation.

Miners earn TAO by:
1. Generating ZK proofs for circuit partitions dispatched by validators
2. Reporting GPU capabilities and maintaining high availability
3. Achieving fast, correct proof generation with high uptime
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

import bittensor as bt

from subnet.base.neuron import BaseNeuron
from subnet.base.checkpoint import Checkpoint
from subnet.protocol.synapses import (
    CapabilityPingSynapse,
    ProofRequestSynapse,
    ProofVerifySynapse,
)

logger = logging.getLogger(__name__)

# Max bytes we'll download for a single IPFS object (256 MB)
_MAX_IPFS_DOWNLOAD_BYTES = 256 * 1024 * 1024
# CIDv0 or CIDv1 regex for basic format validation
_CID_RE_STR = r'^Qm[1-9A-HJ-NP-Za-km-z]{44}$|^b[a-z2-7]{58}$'
import re as _re
_CID_RE = _re.compile(_CID_RE_STR)


class MinerNeuron(BaseNeuron):
    neuron_type = "miner"

    def __init__(self, config: bt.config | None = None) -> None:
        super().__init__(config)

        # Axon — HTTP server that validators query
        self.axon = bt.axon(wallet=self.wallet, config=self.config)

        # Initialize GPU prover engine
        self._prover = None
        self._gpu_info: dict[str, Any] = {}
        self._init_prover()

        # Statistics
        self._start_time = time.monotonic()
        self._total_proofs = 0
        self._successful_proofs = 0
        self._failed_proofs = 0
        self._current_load = 0.0
        self._benchmark_score: float = 0.0

        # State persistence
        self._checkpoint = Checkpoint("miner")
        self._restore_state()

        # Attach handlers
        self.axon.attach(
            forward_fn=self.handle_proof_request,
            blacklist_fn=self.blacklist_proof_request,
            priority_fn=self.priority,
        ).attach(
            forward_fn=self.handle_capability_ping,
            blacklist_fn=self.blacklist_ping,
            priority_fn=self.priority,
        ).attach(
            forward_fn=self.handle_proof_verify,
            blacklist_fn=self.blacklist_verify,
            priority_fn=self.priority,
        )

    def _init_prover(self) -> None:
        """Initialize the Rust/Python prover engine and detect GPUs."""
        try:
            from prover.python.zkml_prover import ProverEngine
            self._prover = ProverEngine()
            devices = self._prover.gpu_devices()
            if devices:
                best = devices[0]
                self._gpu_info = {
                    "gpu_name": best.name,
                    "gpu_backend": best.backend.value,
                    "gpu_count": len(devices),
                    "vram_total_bytes": sum(d.vram_total for d in devices),
                    "vram_available_bytes": sum(d.vram_available for d in devices),
                    "compute_units": best.compute_units,
                    "benchmark_score": best.benchmark_score,
                    "compute_version": getattr(best, "compute_version", ""),
                }
                logger.info("GPU prover initialized: %s (%d devices)", best.name, len(devices))
            else:
                self._gpu_info = {"gpu_name": "CPU", "gpu_backend": "cpu", "gpu_count": 0}
                logger.info("No GPU detected — running CPU prover")
        except ImportError:
            logger.warning("Rust prover engine not available — using Python fallback")
            self._gpu_info = {"gpu_name": "CPU (fallback)", "gpu_backend": "cpu", "gpu_count": 0}

    # ── Forward handlers ─────────────────────────────────────

    async def handle_proof_request(self, synapse: ProofRequestSynapse) -> ProofRequestSynapse:
        """Generate a proof fragment for a circuit partition.

        Flow:
        1. Download circuit partition and witness from IPFS
        2. Load proving key
        3. Run GPU-accelerated proof generation
        4. Return proof fragment and timing data
        """
        # Load shedding: reject when at capacity
        if self._current_load >= 1.0:
            synapse.error = "Miner at capacity — try again later"
            return synapse

        self._current_load = min(1.0, self._current_load + 0.2)
        start = time.monotonic()

        try:
            # Validate CID formats before downloading
            for cid_name, cid_val in [
                ("circuit_cid", synapse.circuit_cid),
                ("witness_cid", synapse.witness_cid),
            ]:
                if not cid_val or not _CID_RE.match(cid_val):
                    synapse.error = f"Invalid {cid_name} format"
                    self._total_proofs += 1
                    self._failed_proofs += 1
                    return synapse
            if synapse.proving_key_cid and not _CID_RE.match(synapse.proving_key_cid):
                synapse.error = "Invalid proving_key_cid format"
                self._total_proofs += 1
                self._failed_proofs += 1
                return synapse

            from prover.python.zkml_prover import (
                ProverEngine, CircuitData, WitnessData, ProofSystem, CircuitType,
            )
            from registry.storage.ipfs import IPFSStorage

            storage = IPFSStorage()

            # Download with size limits to prevent DoS
            circuit_bytes = await storage.download_bytes(synapse.circuit_cid)
            if len(circuit_bytes) > _MAX_IPFS_DOWNLOAD_BYTES:
                raise ValueError(f"Circuit data too large: {len(circuit_bytes)} bytes")
            witness_bytes = await storage.download_bytes(synapse.witness_cid)
            if len(witness_bytes) > _MAX_IPFS_DOWNLOAD_BYTES:
                raise ValueError(f"Witness data too large: {len(witness_bytes)} bytes")
            pk_bytes = b""
            if synapse.proving_key_cid:
                pk_bytes = await storage.download_bytes(synapse.proving_key_cid)

            # Map proof system
            proof_system_map = {
                "groth16": ProofSystem.GROTH16,
                "plonk": ProofSystem.PLONK,
                "halo2": ProofSystem.HALO2,
                "stark": ProofSystem.STARK,
            }
            ps = proof_system_map.get(synapse.proof_system)
            if ps is None:
                logger.warning("Unknown proof_system '%s' — rejecting request", synapse.proof_system)
                synapse.error = f"Unsupported proof system: {synapse.proof_system}"
                self._total_proofs += 1
                self._failed_proofs += 1
                return synapse

            circuit_type_map = {
                "general": CircuitType.GENERAL,
                "evm": CircuitType.EVM,
                "zkml": CircuitType.ZKML,
                "custom": CircuitType.CUSTOM,
            }
            ct = circuit_type_map.get(synapse.circuit_type, CircuitType.GENERAL)

            circuit = CircuitData(
                id=synapse.circuit_cid,
                name=f"partition_{synapse.partition_index}",
                proof_system=ps,
                circuit_type=ct,
                num_constraints=synapse.constraint_end - synapse.constraint_start,
                num_public_inputs=0,
                num_private_inputs=0,
                data=circuit_bytes,
                proving_key=pk_bytes,
                verification_key=b"",
            )
            witness = WitnessData(
                assignments=witness_bytes,
                public_inputs=b"",
            )

            # Generate proof with timeout
            if self._prover is None:
                self._prover = ProverEngine()

            try:
                timeout = synapse.timeout_s if getattr(synapse, 'timeout_s', 0) else 600
                result = await asyncio.wait_for(
                    self._prover.prove(circuit, witness),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Proof generation timed out (600s limit)")

            elapsed_ms = int((time.monotonic() - start) * 1000)
            synapse.proof_fragment = result.data
            synapse.commitment = hashlib.sha256(result.data).digest()
            synapse.generation_time_ms = elapsed_ms
            synapse.gpu_backend_used = result.gpu_backend or self._gpu_info.get("gpu_backend", "cpu")

            self._total_proofs += 1
            self._successful_proofs += 1
            logger.info(
                "Proof fragment generated: job=%s partition=%d/%d time=%dms gpu=%s",
                synapse.job_id, synapse.partition_index, synapse.total_partitions,
                elapsed_ms, synapse.gpu_backend_used,
            )

        except Exception as e:
            self._total_proofs += 1
            self._failed_proofs += 1
            synapse.error = str(e)[:500]
            logger.error("Proof generation failed: job=%s partition=%d error=%s",
                        synapse.job_id, synapse.partition_index, e)
        finally:
            self._current_load = max(0.0, self._current_load - 0.2)

        return synapse

    async def handle_capability_ping(self, synapse: CapabilityPingSynapse) -> CapabilityPingSynapse:
        """Report GPU capabilities and current status."""
        synapse.gpu_name = self._gpu_info.get("gpu_name", "")
        synapse.gpu_backend = self._gpu_info.get("gpu_backend", "cpu")
        synapse.gpu_count = self._gpu_info.get("gpu_count", 0)
        synapse.vram_total_bytes = self._gpu_info.get("vram_total_bytes", 0)
        synapse.vram_available_bytes = self._gpu_info.get("vram_available_bytes", 0)
        synapse.compute_units = self._gpu_info.get("compute_units", 0)
        synapse.benchmark_score = self._benchmark_score or self._gpu_info.get("benchmark_score", 0.0)
        synapse.compute_version = self._gpu_info.get("compute_version", "")
        synapse.supported_proof_types = "groth16,plonk,halo2,stark"
        synapse.max_constraints = 100_000_000  # 100M default
        synapse.current_load = self._current_load
        synapse.total_proofs = self._total_proofs
        synapse.successful_proofs = self._successful_proofs
        synapse.uptime_seconds = int(time.monotonic() - self._start_time)

        if synapse.include_benchmark and self._prover:
            # Run quick benchmark (1K constraint test circuit)
            try:
                from prover.python.zkml_prover import CircuitData, WitnessData, ProofSystem, CircuitType
                bench_circuit = CircuitData(
                    id="benchmark", name="benchmark", proof_system=ProofSystem.GROTH16,
                    circuit_type=CircuitType.GENERAL, num_constraints=1000,
                    num_public_inputs=1, num_private_inputs=10,
                    data=b"\x00" * 1024, proving_key=b"\x00" * 256,
                    verification_key=b"\x00" * 128,
                )
                bench_witness = WitnessData(assignments=b"\x00" * 512, public_inputs=b"\x00" * 32)
                start = time.monotonic()
                await self._prover.prove(bench_circuit, bench_witness)
                elapsed = time.monotonic() - start
                synapse.benchmark_score = 1.0 / max(elapsed, 0.001)
                self._benchmark_score = synapse.benchmark_score
                logger.info("Benchmark completed: score=%.2f (%.3fs)", synapse.benchmark_score, elapsed)
            except Exception as exc:
                synapse.benchmark_score = -1.0
                synapse.error = f"Benchmark failed: {str(exc)[:200]}"
                logger.warning("Benchmark failed: %s", exc)

        return synapse

    async def handle_proof_verify(self, synapse: ProofVerifySynapse) -> ProofVerifySynapse:
        """Verify a proof generated by another miner."""
        start = time.monotonic()
        try:
            # Validate CID formats
            for cid_name, cid_val in [("proof_cid", synapse.proof_cid), ("circuit_cid", synapse.circuit_cid)]:
                if not cid_val or not _CID_RE.match(cid_val):
                    synapse.error = f"Invalid {cid_name} format"
                    return synapse
            if synapse.verification_key_cid and not _CID_RE.match(synapse.verification_key_cid):
                synapse.error = "Invalid verification_key_cid format"
                return synapse

            from prover.python.zkml_prover import (
                ProverEngine, CircuitData, ProofResult, ProofSystem, CircuitType,
            )
            from registry.storage.ipfs import IPFSStorage

            storage = IPFSStorage()
            proof_bytes = await storage.download_bytes(synapse.proof_cid)
            if len(proof_bytes) > _MAX_IPFS_DOWNLOAD_BYTES:
                raise ValueError(f"Proof data too large: {len(proof_bytes)} bytes")

            # Verify content integrity if expected_hash was provided
            if synapse.expected_hash:
                actual_hash = hashlib.sha256(proof_bytes).hexdigest()
                if actual_hash != synapse.expected_hash:
                    synapse.valid = False
                    synapse.error = "Proof data integrity check failed: hash mismatch"
                    synapse.details = "Content hash does not match expected value"
                    return synapse

            circuit_bytes = await storage.download_bytes(synapse.circuit_cid)
            if len(circuit_bytes) > _MAX_IPFS_DOWNLOAD_BYTES:
                raise ValueError(f"Circuit data too large: {len(circuit_bytes)} bytes")
            vk_bytes = b""
            if synapse.verification_key_cid:
                vk_bytes = await storage.download_bytes(synapse.verification_key_cid)

            ps_map = {"groth16": ProofSystem.GROTH16, "plonk": ProofSystem.PLONK,
                       "halo2": ProofSystem.HALO2, "stark": ProofSystem.STARK}
            ps = ps_map.get(synapse.proof_system, ProofSystem.GROTH16)

            circuit = CircuitData(
                id=synapse.circuit_cid, name="verify_target", proof_system=ps,
                circuit_type=CircuitType.GENERAL, num_constraints=0,
                num_public_inputs=0, num_private_inputs=0,
                data=circuit_bytes, proving_key=b"", verification_key=vk_bytes,
            )
            proof = ProofResult(
                proof_system=ps, data=proof_bytes, public_inputs=synapse.public_inputs_json.encode(),
                generation_time_ms=0, proof_size_bytes=len(proof_bytes),
            )

            if self._prover is None:
                self._prover = ProverEngine()
            valid = await self._prover.verify(circuit, proof)

            synapse.valid = valid
            synapse.verification_time_ms = int((time.monotonic() - start) * 1000)
            synapse.details = "Verification passed" if valid else "Verification failed"
        except Exception as e:
            synapse.error = str(e)[:500]
            logger.error("Proof verification failed: %s", e)

        return synapse

    # ── Blacklist & Priority ─────────────────────────────────

    async def blacklist_proof_request(self, synapse: ProofRequestSynapse) -> tuple[bool, str]:
        caller = synapse.dendrite.hotkey
        if caller not in self.metagraph.hotkeys:
            return True, "Not registered"
        uid = self.metagraph.hotkeys.index(caller)
        if self.metagraph.S[uid] < 1.0:
            return True, "Insufficient stake for proof requests"
        return False, ""

    async def blacklist_ping(self, synapse: CapabilityPingSynapse) -> tuple[bool, str]:
        caller = synapse.dendrite.hotkey
        if caller not in self.metagraph.hotkeys:
            return True, "Not registered"
        return False, ""

    async def blacklist_verify(self, synapse: ProofVerifySynapse) -> tuple[bool, str]:
        caller = synapse.dendrite.hotkey
        if caller not in self.metagraph.hotkeys:
            return True, "Not registered"
        uid = self.metagraph.hotkeys.index(caller)
        if self.metagraph.S[uid] < 1.0:
            return True, "Insufficient stake for verification requests"
        return False, ""

    async def priority(self, synapse: bt.Synapse) -> float:
        caller = synapse.dendrite.hotkey
        if caller in self.metagraph.hotkeys:
            uid = self.metagraph.hotkeys.index(caller)
            return float(self.metagraph.S[uid])
        return 0.0

    def _report_stats_to_registry(self) -> None:
        """Best-effort report of miner stats to the registry API."""
        try:
            from sdk.client import ZKMLClient
            from registry.core.config import settings

            with ZKMLClient(
                registry_url=settings.registry_url,
                hotkey=self.wallet.hotkey.ss58_address,
            ) as client:
                client.ping_prover(
                    vram_available_bytes=self._gpu_info.get("vram_available_bytes", 0),
                )
        except Exception as exc:
            logger.debug("Registry stats report failed (non-critical): %s", exc)

    # ── State persistence ────────────────────────────────────

    def _restore_state(self) -> None:
        """Load last checkpoint if available."""
        state = self._checkpoint.load()
        if not state:
            return
        self._total_proofs = state.get("total_proofs", 0)
        self._successful_proofs = state.get("successful_proofs", 0)
        self._failed_proofs = state.get("failed_proofs", 0)
        self._benchmark_score = state.get("benchmark_score", 0.0)
        logger.info(
            "Restored miner state: total=%d success=%d failed=%d",
            self._total_proofs, self._successful_proofs, self._failed_proofs,
        )

    def _save_state(self, *, force: bool = False) -> None:
        """Checkpoint current miner statistics."""
        self._checkpoint.save({
            "total_proofs": self._total_proofs,
            "successful_proofs": self._successful_proofs,
            "failed_proofs": self._failed_proofs,
            "benchmark_score": self._benchmark_score,
            "gpu_info": self._gpu_info,
            "uptime_seconds": int(time.monotonic() - self._start_time),
        }, force=force)

    # ── Lifecycle ────────────────────────────────────────────

    async def forward(self) -> None:
        # Miner forward is passive — axon handles incoming requests
        pass

    def run(self) -> None:
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        self.axon.start()
        logger.info(
            "Prover miner serving on %s:%d  GPU=%s",
            self.axon.external_ip, self.axon.external_port,
            self._gpu_info.get("gpu_name", "none"),
        )

        try:
            while True:
                self.sync()
                self._report_stats_to_registry()
                self._save_state()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Prover miner shutting down — saving state")
            self._save_state(force=True)
        finally:
            self.axon.stop()


def main() -> None:
    neuron = MinerNeuron()
    neuron.run()


if __name__ == "__main__":
    main()
