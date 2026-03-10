"""Modelionn Validator Neuron — dispatches proof jobs and scores provers.

Validators earn TAO by:
1. Dispatching proof requests to GPU-capable miners
2. Monitoring partition completion and aggregating fragments
3. Verifying proofs and scoring miners on correctness, speed, throughput
4. Setting consensus weights that reward the best provers
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import bittensor as bt
import numpy as np

from subnet.base.neuron import BaseNeuron
from subnet.protocol.synapses import (
    CapabilityPingSynapse,
    ProofRequestSynapse,
    ProofVerifySynapse,
)
from subnet.reward.scoring import ProverScore, ProverRewardWeights, compute_prover_rewards

logger = logging.getLogger(__name__)


@dataclass
class ProverInfo:
    """Cached prover capability data."""
    uid: int
    hotkey: str
    gpu_name: str = ""
    gpu_backend: str = "cpu"
    gpu_count: int = 0
    vram_bytes: int = 0
    benchmark_score: float = 0.0
    supported_proofs: str = ""
    current_load: float = 0.0
    total_proofs: int = 0
    last_ping: float = 0.0
    online: bool = False


class ValidatorNeuron(BaseNeuron):
    neuron_type = "validator"

    def __init__(self, config: bt.config | None = None) -> None:
        super().__init__(config)
        self.dendrite = bt.dendrite(wallet=self.wallet)

        n = self.metagraph.n.item() if hasattr(self.metagraph.n, "item") else int(self.metagraph.n)
        self.scores = np.zeros(n, dtype=np.float32)
        self.alpha = self.config.neuron.moving_average_alpha
        self.reward_weights = ProverRewardWeights()

        # Prover tracking
        self._provers: dict[int, ProverInfo] = {}  # uid → info
        self._pending_jobs: dict[str, dict] = {}  # job_id → state
        self._step = 0

        # Intervals
        self.PING_INTERVAL_STEPS = 5  # Ping every 5 steps (~60s)
        self.WEIGHT_SET_INTERVAL = 100
        self._steps_since_weight_set = 0

    # ── Main loop ────────────────────────────────────────────

    async def forward(self) -> None:
        """One validation cycle:

        1. Ping miners for capabilities (periodically)
        2. Dispatch pending proof jobs to available provers
        3. Check for completed partitions
        4. Verify completed proofs cross-prover
        5. Score provers and update weights
        """
        self._step += 1

        # 1. Ping for capabilities at regular intervals
        if self._step % self.PING_INTERVAL_STEPS == 1:
            await self._ping_all_miners()

        # 2 & 3. Dispatch and monitor jobs
        await self._monitor_jobs()

        # 4. Score online provers
        prover_scores = self._compute_scores()

        # 5. Update EMA scores
        if prover_scores:
            rewards = compute_prover_rewards(prover_scores, self.reward_weights)
            for score, reward in zip(prover_scores, rewards):
                self.scores[score.uid] = (
                    self.alpha * reward + (1 - self.alpha) * self.scores[score.uid]
                )

        # 6. Set weights
        self._steps_since_weight_set += 1
        if self._steps_since_weight_set >= self.WEIGHT_SET_INTERVAL:
            self._set_weights()
            self._steps_since_weight_set = 0

    # ── Capability pinging ───────────────────────────────────

    async def _ping_all_miners(self) -> None:
        """Ping all registered miners for their GPU capabilities."""
        n = self.metagraph.n.item() if hasattr(self.metagraph.n, "item") else int(self.metagraph.n)
        uids = list(range(n))
        axons = [self.metagraph.axons[uid] for uid in uids]

        # Send capability pings in batch
        responses = await self.dendrite(
            axons=axons,
            synapse=CapabilityPingSynapse(include_benchmark=False),
            timeout=15,
        )

        now = time.monotonic()
        online_count = 0
        for uid, response in zip(uids, responses):
            if not response.is_success:
                if uid in self._provers:
                    self._provers[uid].online = False
                continue

            info = ProverInfo(
                uid=uid,
                hotkey=self.metagraph.hotkeys[uid],
                gpu_name=response.gpu_name or "",
                gpu_backend=response.gpu_backend or "cpu",
                gpu_count=response.gpu_count or 0,
                vram_bytes=response.vram_total_bytes or 0,
                benchmark_score=response.benchmark_score or 0.0,
                supported_proofs=response.supported_proof_types or "",
                current_load=response.current_load or 0.0,
                total_proofs=response.total_proofs or 0,
                last_ping=now,
                online=True,
            )
            self._provers[uid] = info
            online_count += 1

        logger.info("Prover ping: %d/%d online", online_count, n)

    # ── Job dispatching & monitoring ─────────────────────────

    async def dispatch_proof_job(
        self, job_id: str, circuit_cid: str, witness_cid: str,
        proving_key_cid: str, proof_system: str, circuit_type: str,
        num_partitions: int, constraint_count: int, redundancy: int = 2,
    ) -> None:
        """Dispatch a proof job to available provers.

        Partitions the circuit and assigns partitions to online miners
        with lowest current load and best benchmark scores.
        """
        # Select the best available provers
        online = sorted(
            [p for p in self._provers.values() if p.online],
            key=lambda p: (-p.benchmark_score, p.current_load),
        )
        if not online:
            logger.warning("No online provers for job %s", job_id)
            return

        constraints_per_part = constraint_count // max(num_partitions, 1)
        partitions: list[dict] = []

        for part_idx in range(num_partitions):
            start = part_idx * constraints_per_part
            end = (part_idx + 1) * constraints_per_part if part_idx < num_partitions - 1 else constraint_count

            # Assign to prover with round-robin over best provers
            for r in range(redundancy):
                prover = online[(part_idx * redundancy + r) % len(online)]
                axon = self.metagraph.axons[prover.uid]

                synapse = ProofRequestSynapse(
                    job_id=job_id,
                    circuit_cid=circuit_cid,
                    partition_index=part_idx,
                    total_partitions=num_partitions,
                    constraint_start=start,
                    constraint_end=end,
                    witness_cid=witness_cid,
                    proving_key_cid=proving_key_cid,
                    proof_system=proof_system,
                    circuit_type=circuit_type,
                )

                partitions.append({
                    "partition_index": part_idx,
                    "redundancy_index": r,
                    "prover_uid": prover.uid,
                    "axon": axon,
                    "synapse": synapse,
                    "status": "dispatched",
                    "result": None,
                })

        self._pending_jobs[job_id] = {
            "job_id": job_id,
            "circuit_cid": circuit_cid,
            "proof_system": proof_system,
            "num_partitions": num_partitions,
            "redundancy": redundancy,
            "partitions": partitions,
            "started_at": time.monotonic(),
            "status": "dispatched",
        }

        # Fire off all proof requests concurrently
        tasks = []
        for part in partitions:
            tasks.append(self._send_proof_request(job_id, part))
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "Job %s dispatched: %d partitions × %d redundancy → %d requests to %d provers",
            job_id, num_partitions, redundancy, len(partitions), len(online),
        )

    async def _send_proof_request(self, job_id: str, partition: dict) -> None:
        """Send a single proof request to a prover."""
        try:
            responses = await self.dendrite(
                axons=[partition["axon"]],
                synapse=partition["synapse"],
                timeout=600,  # Up to 10 minutes for large circuits
            )
            if responses and responses[0].is_success:
                resp = responses[0]
                partition["status"] = "completed"
                partition["result"] = {
                    "proof_fragment": resp.proof_fragment,
                    "commitment": resp.commitment,
                    "generation_time_ms": resp.generation_time_ms,
                    "gpu_backend_used": resp.gpu_backend_used,
                }
            else:
                partition["status"] = "failed"
                partition["result"] = {
                    "error": getattr(responses[0], "error", "Unknown") if responses else "No response"
                }
        except Exception as e:
            partition["status"] = "failed"
            partition["result"] = {"error": str(e)[:500]}

    async def _monitor_jobs(self) -> None:
        """Check pending jobs for completed partition sets and aggregate."""
        completed_jobs = []
        for job_id, job in self._pending_jobs.items():
            if job["status"] != "dispatched":
                continue

            parts = job["partitions"]
            n_parts = job["num_partitions"]

            # Check if every partition has at least one successful result
            partition_done = {}
            for part in parts:
                pidx = part["partition_index"]
                if pidx not in partition_done and part["status"] == "completed":
                    partition_done[pidx] = part

            if len(partition_done) >= n_parts:
                # All partitions have at least one result — verify
                await self._verify_and_finalize_job(job_id, job, partition_done)
                completed_jobs.append(job_id)
            elif all(p["status"] in ("completed", "failed") for p in parts):
                # All requests responded but some partitions have no success
                missing = set(range(n_parts)) - set(partition_done.keys())
                logger.error("Job %s failed: missing partitions %s", job_id, missing)
                job["status"] = "failed"
                completed_jobs.append(job_id)

        for jid in completed_jobs:
            if self._pending_jobs[jid]["status"] not in ("completed", "failed"):
                self._pending_jobs[jid]["status"] = "completed"

    async def _verify_and_finalize_job(
        self, job_id: str, job: dict, partition_done: dict[int, dict],
    ) -> None:
        """Cross-verify proof fragments by asking other miners to verify."""
        # For each partition, pick a different prover to verify
        online = [p for p in self._provers.values() if p.online]
        if len(online) < 2:
            # Not enough provers for cross-verification, accept as-is
            job["status"] = "completed"
            logger.info("Job %s completed (no cross-verification, <2 provers)", job_id)
            return

        verified_count = 0
        for pidx, part in partition_done.items():
            result = part["result"]
            if not result or not result.get("proof_fragment"):
                continue

            # Upload fragment to IPFS (simulated — in production this calls IPFS)
            fragment_hash = hashlib.sha256(result["proof_fragment"]).hexdigest()

            # Ask a different prover to verify
            generating_uid = part["prover_uid"]
            verifiers = [p for p in online if p.uid != generating_uid]
            if not verifiers:
                verified_count += 1
                continue

            verifier = verifiers[0]
            verify_synapse = ProofVerifySynapse(
                proof_cid=fragment_hash,
                circuit_cid=job["circuit_cid"],
                proof_system=job["proof_system"],
            )
            try:
                responses = await self.dendrite(
                    axons=[self.metagraph.axons[verifier.uid]],
                    synapse=verify_synapse,
                    timeout=60,
                )
                if responses and responses[0].is_success and responses[0].valid:
                    verified_count += 1
                else:
                    logger.warning(
                        "Job %s partition %d verification failed by uid=%d",
                        job_id, pidx, verifier.uid,
                    )
            except Exception as e:
                logger.error("Verification request failed: %s", e)

        total = len(partition_done)
        if verified_count >= total * 0.7:
            job["status"] = "completed"
            elapsed = time.monotonic() - job["started_at"]
            logger.info("Job %s completed and verified (%d/%d partitions) in %.1fs",
                       job_id, verified_count, total, elapsed)
        else:
            job["status"] = "failed"
            logger.warning("Job %s verification failed (%d/%d)", job_id, verified_count, total)

    # ── Scoring ──────────────────────────────────────────────

    def _compute_scores(self) -> list[ProverScore]:
        """Compute scores for all tracked provers."""
        scores: list[ProverScore] = []

        for uid, prover in self._provers.items():
            if not prover.online:
                continue

            # Count successful/failed proofs from recent jobs
            successful = 0
            failed = 0
            total_time_ms = 0
            proof_count = 0
            for job in self._pending_jobs.values():
                for part in job.get("partitions", []):
                    if part["prover_uid"] != uid:
                        continue
                    if part["status"] == "completed":
                        successful += 1
                        result = part.get("result", {})
                        if result and result.get("generation_time_ms"):
                            total_time_ms += result["generation_time_ms"]
                            proof_count += 1
                    elif part["status"] == "failed":
                        failed += 1

            total = successful + failed
            correctness = successful / max(total, 1)
            avg_speed_ms = total_time_ms / max(proof_count, 1)
            # Speed score: faster = higher (normalize against 60s baseline)
            speed = max(0.0, 1.0 - (avg_speed_ms / 60_000))
            throughput = min(1.0, proof_count / 10.0)  # Normalize against 10 proofs
            reliability = 1.0 if prover.online and total > 0 else 0.0
            # GPU efficiency bonus
            efficiency = min(1.0, prover.benchmark_score / 100.0)

            scores.append(ProverScore(
                uid=uid,
                correctness=correctness,
                speed=speed,
                throughput=throughput,
                reliability=reliability,
                efficiency=efficiency,
            ))

        return scores

    # ── Weight setting ───────────────────────────────────────

    def _set_weights(self) -> None:
        """Normalize scores and set weights on-chain."""
        norm = np.linalg.norm(self.scores, ord=1)
        if norm == 0:
            return

        weights = self.scores / norm
        uids = np.arange(len(weights))

        mask = weights > 0
        if not mask.any():
            return

        try:
            self.subtensor.set_weights(
                wallet=self.wallet,
                netuid=self.config.netuid,
                uids=uids[mask].tolist(),
                weights=weights[mask].tolist(),
                wait_for_finalization=True,
            )
            logger.info("Weights set: %d non-zero entries", int(mask.sum()))
        except Exception as e:
            logger.error("Failed to set weights: %s", e)

    # ── Lifecycle ────────────────────────────────────────────

    def run(self) -> None:
        logger.info("Validator starting — proof dispatcher mode")
        loop = asyncio.get_event_loop()
        step = 0
        try:
            while True:
                logger.info("Validator step %d  provers=%d  pending_jobs=%d",
                           step, len([p for p in self._provers.values() if p.online]),
                           len([j for j in self._pending_jobs.values() if j["status"] == "dispatched"]))
                loop.run_until_complete(self.forward())
                self.sync()
                step += 1
                time.sleep(12 * self.config.neuron.epoch_length)
        except KeyboardInterrupt:
            logger.info("Validator shutting down")


def main() -> None:
    neuron = ValidatorNeuron()
    neuron.run()


if __name__ == "__main__":
    main()
