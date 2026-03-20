"""ZKML Validator Neuron — dispatches proof jobs and scores provers.

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
from subnet.base.checkpoint import Checkpoint
from subnet.protocol.synapses import (
    CapabilityPingSynapse,
    CommitRevealSynapse,
    ProofRequestSynapse,
    ProofVerifySynapse,
)
from subnet.consensus.engine import ConsensusEngine, VerificationVote
from subnet.reward.scoring import ProverScore, ProverRewardWeights, compute_prover_rewards
from subnet.reward.anti_sybil import ProofHashDeduplicator, BenchmarkVerifier

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
        self.axon = bt.axon(wallet=self.wallet, config=self.config)

        n = self.metagraph.n.item() if hasattr(self.metagraph.n, "item") else int(self.metagraph.n)
        self.scores = np.zeros(n, dtype=np.float32)
        self.alpha = self.config.neuron.moving_average_alpha
        self.reward_weights = ProverRewardWeights()

        # Configurable scoring baselines — override via neuron config
        self._speed_baseline_ms: float = getattr(
            self.config.neuron, "speed_baseline_ms", 60_000
        )  # ms — proofs faster than this score highly
        self._throughput_baseline: int = getattr(
            self.config.neuron, "throughput_baseline", 10
        )  # proof count — normalize throughput against this

        # Prover tracking
        self._provers: dict[int, ProverInfo] = {}  # uid → info
        self._pending_jobs: dict[str, dict] = {}  # job_id → state
        self._step = 0
        self._MAX_COMPLETED_AGE = 600  # seconds before evicting finished jobs

        # Intervals
        self.PING_INTERVAL_STEPS = 5  # Ping every 5 steps (~60s)
        self.WEIGHT_SET_INTERVAL = 100
        self._steps_since_weight_set = 0

        # Consensus engine for multi-validator proof verification
        self._consensus = ConsensusEngine()

        # Proof hash deduplication to prevent fragment reuse across jobs
        self._deduplicator = ProofHashDeduplicator()

        # GPU benchmark proof-of-work verifier
        self._benchmark_verifier = BenchmarkVerifier(cache_ttl_s=3600)

        # How often to run PoW challenges (every N ping cycles)
        self._POW_CHALLENGE_INTERVAL = 3  # every 3rd ping cycle
        self._pow_cycle_counter = 0

        # Commit-reveal store for anti-frontrunning
        # Maps commit_hash → {hotkey, artifact_name, timestamp}
        self._commits: dict[str, dict] = {}
        self._COMMIT_EXPIRY_S = 600  # Commits expire after 10 minutes

        # State persistence
        self._checkpoint = Checkpoint("validator")
        self._restore_state()

    # ── State persistence ────────────────────────────────────

    def _restore_state(self) -> None:
        """Load last checkpoint if available."""
        state = self._checkpoint.load()
        if not state:
            return
        # Restore prover info
        for uid_str, info in state.get("provers", {}).items():
            uid = int(uid_str)
            self._provers[uid] = ProverInfo(
                uid=uid,
                hotkey=info.get("hotkey", ""),
                gpu_name=info.get("gpu_name", ""),
                gpu_backend=info.get("gpu_backend", "cpu"),
                gpu_count=info.get("gpu_count", 0),
                vram_bytes=info.get("vram_bytes", 0),
                benchmark_score=info.get("benchmark_score", 0.0),
                supported_proofs=info.get("supported_proofs", ""),
                current_load=0.0,  # reset load on restart
                total_proofs=info.get("total_proofs", 0),
                last_ping=0.0,
                online=False,  # require fresh ping
            )
        # Restore scores array
        if "scores" in state:
            import json
            score_list = state["scores"]
            for i, val in enumerate(score_list):
                if i < len(self.scores):
                    self.scores[i] = float(val)
        logger.info("Restored state: %d provers, scores loaded", len(self._provers))

    def _save_state(self, *, force: bool = False) -> None:
        """Checkpoint current state."""
        provers_data = {}
        for uid, p in self._provers.items():
            provers_data[str(uid)] = {
                "hotkey": p.hotkey,
                "gpu_name": p.gpu_name,
                "gpu_backend": p.gpu_backend,
                "gpu_count": p.gpu_count,
                "vram_bytes": p.vram_bytes,
                "benchmark_score": p.benchmark_score,
                "supported_proofs": p.supported_proofs,
                "total_proofs": p.total_proofs,
            }
        self._checkpoint.save({
            "provers": provers_data,
            "scores": self.scores.tolist(),
            "step": self._step,
        }, force=force)

        # Expose commit-reveal over axon for anti-frontrunning protocol.
        self.axon.attach(
            forward_fn=self.handle_commit_reveal,
            blacklist_fn=self.blacklist_commit_reveal,
            priority_fn=self.priority,
        )

    # ── Commit-reveal anti-frontrunning ──────────────────────

    def handle_commit(self, hotkey: str, artifact_name: str, commit_hash: str) -> dict:
        """Record a commitment hash for later reveal (internal use)."""
        # Evict expired commits
        now = time.monotonic()
        stale = [h for h, c in self._commits.items() if now - c["timestamp"] > self._COMMIT_EXPIRY_S]
        for h in stale:
            del self._commits[h]

        if commit_hash in self._commits:
            return {"accepted": False, "is_earliest": False, "error": "Duplicate commit hash"}

        is_earliest = not any(
            c["artifact_name"] == artifact_name for c in self._commits.values()
        )
        self._commits[commit_hash] = {
            "hotkey": hotkey,
            "artifact_name": artifact_name,
            "timestamp": now,
        }
        logger.info("Commit recorded: %s from %s (earliest=%s)", commit_hash[:16], hotkey[:12], is_earliest)
        return {"accepted": True, "is_earliest": is_earliest, "error": ""}

    def handle_reveal(self, hotkey: str, artifact_name: str, artifact_hash: str, nonce: str) -> dict:
        """Phase 2: Verify that the reveal matches a prior commitment.

        Checks that SHA256(name || artifact_hash || nonce) matches a stored commit
        from the same hotkey.
        """
        # Evict expired commits (same as handle_commit to prevent leaks)
        now = time.monotonic()
        stale = [h for h, c in self._commits.items() if now - c["timestamp"] > self._COMMIT_EXPIRY_S]
        for h in stale:
            del self._commits[h]

        expected_hash = hashlib.sha256(
            f"{artifact_name}{artifact_hash}{nonce}".encode()
        ).hexdigest()

        commit = self._commits.get(expected_hash)
        if not commit:
            return {"accepted": False, "is_earliest": False, "error": "No matching commit found"}
        if commit["hotkey"] != hotkey:
            return {"accepted": False, "is_earliest": False, "error": "Commit/reveal hotkey mismatch"}

        # Valid reveal — check if this was the first commit for the artifact
        is_earliest = True
        for ch, c in self._commits.items():
            if c["artifact_name"] == artifact_name and c["timestamp"] < commit["timestamp"]:
                is_earliest = False
                break

        # Clean up the used commit
        del self._commits[expected_hash]

        logger.info("Reveal accepted: %s from %s (earliest=%s)", artifact_hash[:16], hotkey[:12], is_earliest)
        return {"accepted": True, "is_earliest": is_earliest, "error": ""}

    async def handle_commit_reveal(self, synapse: CommitRevealSynapse) -> CommitRevealSynapse:
        """Axon handler for two-phase commit-reveal requests."""
        caller = getattr(getattr(synapse, "dendrite", None), "hotkey", "")
        if synapse.phase == "commit":
            result = self.handle_commit(caller, synapse.artifact_name, synapse.commit_hash)
        elif synapse.phase == "reveal":
            result = self.handle_reveal(
                caller,
                synapse.artifact_name,
                synapse.artifact_hash,
                synapse.nonce,
            )
        else:
            result = {"accepted": False, "is_earliest": False, "error": "Invalid phase"}

        synapse.accepted = result["accepted"]
        synapse.is_earliest = result["is_earliest"]
        synapse.error = result["error"]
        return synapse

    async def blacklist_commit_reveal(self, synapse: CommitRevealSynapse) -> tuple[bool, str]:
        caller = getattr(getattr(synapse, "dendrite", None), "hotkey", "")
        if caller not in self.metagraph.hotkeys:
            return True, "Not registered"
        return False, ""

    async def priority(self, synapse: bt.Synapse) -> float:
        caller = getattr(getattr(synapse, "dendrite", None), "hotkey", "")
        if caller in self.metagraph.hotkeys:
            uid = self.metagraph.hotkeys.index(caller)
            return float(self.metagraph.S[uid])
        return 0.0

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
            # Sync scores to registry DB (best-effort)
            await self._sync_scores_to_registry(prover_scores)

        # 6. Set weights
        self._steps_since_weight_set += 1
        if self._steps_since_weight_set >= self.WEIGHT_SET_INTERVAL:
            self._set_weights()
            self._steps_since_weight_set = 0

        # 7. Periodic checkpoint
        self._save_state()

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

        # Periodically run PoW benchmark challenges on online miners
        self._pow_cycle_counter += 1
        if self._pow_cycle_counter >= self._POW_CHALLENGE_INTERVAL:
            self._pow_cycle_counter = 0
            await self._run_benchmark_challenges()

    async def _run_benchmark_challenges(self) -> None:
        """Send small test proof jobs to miners that need benchmark verification.

        Selects miners whose benchmark is uncached or expired and sends
        a CapabilityPingSynapse with include_benchmark=True.  The response
        contains generation_time derived by the miner's own benchmark run,
        which we cross-check against the claimed score.
        """
        candidates = [
            p for p in self._provers.values()
            if p.online and self._benchmark_verifier.needs_verification(p.hotkey)
        ]
        if not candidates:
            return

        # Limit batch size to avoid flooding the network
        candidates = candidates[:10]
        axons = [self.metagraph.axons[p.uid] for p in candidates]

        responses = await self.dendrite(
            axons=axons,
            synapse=CapabilityPingSynapse(include_benchmark=True),
            timeout=30,
        )

        for prover, response in zip(candidates, responses):
            if not response.is_success or response.benchmark_score <= 0:
                # Miner failed the challenge — mark as untrusted
                self._benchmark_verifier.record(
                    prover.hotkey, prover.benchmark_score, float("inf"),
                )
                continue

            # The miner ran the benchmark and reported an achieved score.
            # Compute effective prove time from the reported score.
            effective_time = 1.0 / max(response.benchmark_score, 0.001)
            passed = self._benchmark_verifier.record(
                prover.hotkey, prover.benchmark_score, effective_time,
            )
            if passed:
                # Update prover's benchmark with the verified score
                prover.benchmark_score = response.benchmark_score

        verified_count = sum(
            1 for p in candidates
            if self._benchmark_verifier.is_trusted(p.hotkey)
        )
        logger.info(
            "Benchmark PoW: %d/%d miners verified",
            verified_count, len(candidates),
        )

    # ── Job dispatching & monitoring ─────────────────────────

    async def dispatch_proof_job(
        self, job_id: str, circuit_cid: str, witness_cid: str,
        proving_key_cid: str, proof_system: str, circuit_type: str,
        num_partitions: int, constraint_count: int, redundancy: int = 2,
    ) -> dict:
        """Dispatch a proof job to available provers.

        Partitions the circuit and assigns partitions to online miners
        with lowest current load and best benchmark scores.

        Returns a dict with 'status' key ('dispatched', 'no_miners', etc.).
        """
        # Select the best available provers — prefer benchmark-verified miners
        online = sorted(
            [p for p in self._provers.values() if p.online],
            key=lambda p: (
                not self._benchmark_verifier.is_trusted(p.hotkey),  # verified first
                -p.benchmark_score,
                p.current_load,
            ),
        )
        if not online:
            logger.error("No online provers for job %s — job cannot be dispatched", job_id)
            return {"status": "no_miners", "job_id": job_id, "error": "No online provers available"}

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
        return {"status": "dispatched", "job_id": job_id, "partitions": len(partitions)}

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

        # Evict old completed/failed jobs to prevent memory leaks
        now = time.monotonic()
        stale = [
            jid for jid, job in self._pending_jobs.items()
            if job["status"] in ("completed", "failed")
            and now - job.get("started_at", now) > self._MAX_COMPLETED_AGE
        ]
        for jid in stale:
            del self._pending_jobs[jid]

        # Periodic cleanup of consensus engine state
        self._consensus.cleanup()

    async def _verify_and_finalize_job(
        self, job_id: str, job: dict, partition_done: dict[int, dict],
    ) -> None:
        """Cross-verify proof fragments using multi-validator consensus engine."""
        online = [p for p in self._provers.values() if p.online]
        if len(online) < 2:
            job["status"] = "completed"
            logger.info("Job %s completed (no cross-verification, <2 provers)", job_id)
            return

        # Build stake map from metagraph
        stakes: dict[str, float] = {}
        for p in online:
            try:
                stakes[p.hotkey] = float(self.metagraph.S[p.uid])
            except Exception:
                stakes[p.hotkey] = 1.0

        verified_count = 0
        total = len(partition_done)

        for pidx, part in partition_done.items():
            result = part["result"]
            if not result or not result.get("proof_fragment"):
                continue

            fragment_data = result["proof_fragment"]
            if isinstance(fragment_data, str):
                fragment_data = fragment_data.encode()
            fragment_hash = hashlib.sha256(fragment_data).hexdigest()

            # Check for duplicate proof fragment reuse across jobs/partitions
            if not self._deduplicator.check_and_record(fragment_hash, job_id, pidx):
                logger.warning(
                    "Job %s partition %d: duplicate proof fragment detected (hash=%s)",
                    job_id, pidx, fragment_hash[:16],
                )
                continue

            proof_cid = result.get("commitment") or fragment_hash

            # Select verifiers via consensus engine (excluding the generator)
            generating_uid = part["prover_uid"]
            candidates = [p.hotkey for p in online if p.uid != generating_uid]
            if not candidates:
                verified_count += 1
                continue

            verifiers = self._consensus.assign_verifiers(job_id, candidates, stakes)

            # Send verification requests to all assigned verifiers in parallel
            verify_synapse = ProofVerifySynapse(
                proof_cid=proof_cid,
                circuit_cid=job["circuit_cid"],
                proof_system=job["proof_system"],
                expected_hash=fragment_hash,
            )
            hotkey_to_uid = {p.hotkey: p.uid for p in online}
            verify_tasks = []
            for v_hotkey in verifiers:
                v_uid = hotkey_to_uid.get(v_hotkey)
                if v_uid is None:
                    continue
                verify_tasks.append(
                    self._request_verification(v_uid, v_hotkey, job_id, pidx, verify_synapse)
                )

            votes = await asyncio.gather(*verify_tasks, return_exceptions=True)
            for v in votes:
                if isinstance(v, VerificationVote):
                    self._consensus.submit_vote(v)

            # Compute consensus for this partition
            consensus = self._consensus.compute_consensus(job_id, pidx, stakes)
            if consensus and consensus.reached_consensus and consensus.consensus_valid:
                verified_count += 1
            elif consensus:
                logger.warning(
                    "Job %s partition %d consensus: valid=%s ratio=%.2f quorum=%d",
                    job_id, pidx, consensus.consensus_valid,
                    consensus.agreement_ratio, consensus.quorum_size,
                )
            else:
                logger.warning("Job %s partition %d: insufficient votes for consensus", job_id, pidx)

        if verified_count >= total * 0.7:
            job["status"] = "completed"
            elapsed = time.monotonic() - job["started_at"]
            logger.info("Job %s completed and verified (%d/%d partitions) in %.1fs",
                       job_id, verified_count, total, elapsed)
        else:
            job["status"] = "failed"
            logger.warning("Job %s verification failed (%d/%d)", job_id, verified_count, total)

    async def _request_verification(
        self, verifier_uid: int, verifier_hotkey: str,
        job_id: str, partition_index: int, synapse: ProofVerifySynapse,
    ) -> VerificationVote:
        """Send a verification request to a single verifier and return a vote."""
        start = time.monotonic()
        try:
            responses = await self.dendrite(
                axons=[self.metagraph.axons[verifier_uid]],
                synapse=synapse,
                timeout=60,
            )
            valid = bool(responses and responses[0].is_success and responses[0].valid)
        except Exception as e:
            logger.error("Verification request to uid=%d failed: %s", verifier_uid, e)
            valid = False

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return VerificationVote(
            validator_hotkey=verifier_hotkey,
            job_id=job_id,
            partition_index=partition_index,
            valid=valid,
            verification_time_ms=elapsed_ms,
        )

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
            # Speed score: faster = higher (normalize against configurable baseline)
            speed = max(0.0, 1.0 - (avg_speed_ms / self._speed_baseline_ms))
            throughput = min(1.0, proof_count / max(self._throughput_baseline, 1))
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

    # ── Registry score sync ─────────────────────────────────

    async def _sync_scores_to_registry(self, prover_scores: list[ProverScore]) -> None:
        """Push prover scores to the registry so the API can serve rankings."""
        try:
            from registry.core.deps import async_session
            from registry.models.database import ProverCapabilityRow
            from sqlalchemy import select

            async with async_session() as db:
                for score in prover_scores:
                    prover = self._provers.get(score.uid)
                    if not prover:
                        continue
                    row = (
                        await db.execute(
                            select(ProverCapabilityRow).where(
                                ProverCapabilityRow.hotkey == prover.hotkey
                            )
                        )
                    ).scalar_one_or_none()
                    if row:
                        row.benchmark_score = score.total(self.reward_weights) * 100
                    else:
                        # Prover hasn't registered via API — create a stub row
                        row = ProverCapabilityRow(
                            hotkey=prover.hotkey,
                            gpu_name=prover.gpu_name,
                            gpu_backend=prover.gpu_backend,
                            gpu_count=prover.gpu_count,
                            vram_total_bytes=prover.vram_bytes,
                            benchmark_score=score.total(self.reward_weights) * 100,
                            online=prover.online,
                        )
                        db.add(row)
                await db.commit()
        except Exception as exc:
            logger.debug("Registry score sync failed (non-critical): %s", exc)

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
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        self.axon.start()
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
            logger.info("Validator shutting down — saving state")
            self._save_state(force=True)
        finally:
            self.axon.stop()


def main() -> None:
    neuron = ValidatorNeuron()
    neuron.run()


if __name__ == "__main__":
    main()
