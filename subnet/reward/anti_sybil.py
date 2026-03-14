"""Anti-Sybil mechanisms — stake checks, rate limiting, GPU benchmark gating."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

import numpy as np

from registry.core.config import settings

logger = logging.getLogger(__name__)


class StakeGate:
    """Reject provers/requesters whose stake is below the minimum threshold."""

    def __init__(self, min_stake: float | None = None) -> None:
        self.min_stake = min_stake if min_stake is not None else settings.min_stake_to_publish

    def check(self, stake: float, hotkey: str) -> bool:
        if stake < self.min_stake:
            logger.warning("Stake gate: %s has %.4f TAO, need %.4f", hotkey, stake, self.min_stake)
            return False
        return True


class RateLimiter:
    """Limit how many proof requests a hotkey can submit per time window.

    Note: This uses wall-clock time (epoch_seconds), NOT the neuron's
    epoch_length (which counts validation steps). The two are independent:

    - epoch_seconds (default 3600): sliding window in real seconds
    - neuron.epoch_length (default 100): number of validation steps per epoch

    At ~12s per step, 100 steps ≈ 20 minutes. The rate limiter's 1-hour
    window is intentionally broader to smooth out burst traffic.
    """

    def __init__(self, max_per_epoch: int = 50, epoch_seconds: int = 3600) -> None:
        self.max_per_epoch = max_per_epoch
        self.epoch_seconds = epoch_seconds
        self._counts: dict[str, list[float]] = defaultdict(list)

    def allow(self, hotkey: str) -> bool:
        now = time.time()
        window = now - self.epoch_seconds
        self._counts[hotkey] = [t for t in self._counts[hotkey] if t > window]
        if len(self._counts[hotkey]) >= self.max_per_epoch:
            logger.warning("Rate limit: %s exceeded %d requests/epoch", hotkey, self.max_per_epoch)
            return False
        self._counts[hotkey].append(now)
        return True


class GpuBenchmarkGate:
    """Require miners to meet a minimum GPU benchmark score before accepting proof jobs.

    Prevents CPU-only nodes from consuming proof dispatch slots they
    cannot complete efficiently.
    """

    def __init__(self, min_benchmark_score: float = 1.0) -> None:
        self.min_benchmark_score = min_benchmark_score

    def check(self, benchmark_score: float, hotkey: str) -> bool:
        if benchmark_score < self.min_benchmark_score:
            logger.warning(
                "GPU gate: %s benchmark %.2f below minimum %.2f",
                hotkey, benchmark_score, self.min_benchmark_score,
            )
            return False
        return True


class ProofHashDeduplicator:
    """Detect duplicate proof submissions by comparing proof hashes.

    Prevents miners from reusing proof fragments across different jobs
    or partitions.
    """

    def __init__(self, max_history: int = 10000) -> None:
        self._proof_hashes: dict[str, str] = {}  # hash → "job_id:partition"
        self._max = max_history

    def check_and_record(self, proof_hash: str, job_id: str, partition_index: int) -> bool:
        """Returns True if unique, False if duplicate."""
        key = f"{job_id}:{partition_index}"
        if proof_hash in self._proof_hashes:
            existing = self._proof_hashes[proof_hash]
            if existing != key:
                logger.warning("Duplicate proof hash %s (existing=%s, new=%s)", proof_hash, existing, key)
                return False
        if len(self._proof_hashes) >= self._max:
            # Evict oldest entries (simple FIFO via dict ordering)
            to_remove = list(self._proof_hashes.keys())[:self._max // 4]
            for k in to_remove:
                del self._proof_hashes[k]
        self._proof_hashes[proof_hash] = key
        return True
