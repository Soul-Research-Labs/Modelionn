"""Multi-factor reward function for the ZKML ZK prover subnet.

Prover scoring formula:
    reward = w₁·correctness + w₂·speed + w₃·throughput + w₄·reliability + w₅·efficiency

All individual scores are normalized to [0, 1].
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ZK Prover scoring (primary)
# ---------------------------------------------------------------------------

@dataclass
class ProverRewardWeights:
    correctness: float = 0.35
    speed: float = 0.30
    throughput: float = 0.20
    reliability: float = 0.10
    efficiency: float = 0.05


@dataclass
class ProverScore:
    uid: int
    correctness: float = 0.0   # Fraction of valid proofs
    speed: float = 0.0         # Normalized generation speed (faster = higher)
    throughput: float = 0.0    # Number of proofs relative to peers
    reliability: float = 0.0   # Uptime and availability
    efficiency: float = 0.0    # GPU utilization / benchmark score

    def total(self, w: ProverRewardWeights | None = None) -> float:
        w = w or ProverRewardWeights()
        return max(0.0, (
            w.correctness * self.correctness
            + w.speed * self.speed
            + w.throughput * self.throughput
            + w.reliability * self.reliability
            + w.efficiency * self.efficiency
        ))


def compute_prover_rewards(
    scores: list[ProverScore],
    weights: ProverRewardWeights | None = None,
) -> list[float]:
    """Return a reward list in [0, 1] for each prover score."""
    w = weights or ProverRewardWeights()
    raw = np.array([s.total(w) for s in scores], dtype=np.float32)
    total = raw.sum()
    if total > 0:
        raw /= total
    return raw.tolist()
