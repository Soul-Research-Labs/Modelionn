"""Multi-validator proof verification consensus engine.

For ZK proofs, consensus is binary: a proof is either valid or invalid.
Multiple validators verify the same proof independently, and the network
accepts the proof if a quorum of validators agree on validity.

Tracks validator reliability and penalizes validators that consistently
disagree with the majority.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Consensus parameters
MIN_QUORUM = 2                  # Minimum validators for proof consensus
CONSENSUS_THRESHOLD = 0.66      # 66% agreement required
MAX_VALIDATORS_PER_PROOF = 5    # Maximum validators verifying a single proof
DIVERGENCE_WINDOW = 50          # Rolling window for divergence tracking
SLASH_THRESHOLD = 0.20          # Slash if >20% divergence rate


@dataclass
class VerificationVote:
    """A single validator's proof verification vote."""
    validator_hotkey: str
    job_id: str
    partition_index: int
    valid: bool
    verification_time_ms: int = 0
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


@dataclass
class ProofConsensusResult:
    """Result of consensus computation for a proof verification."""
    job_id: str
    partition_index: int
    consensus_valid: bool           # Final consensus: proof is valid or not
    agreement_ratio: float          # Fraction of agreeing validators
    quorum_size: int                # Number of voters
    agreeing_validators: list[str]  # Hotkeys that agreed with consensus
    diverging_validators: list[str] # Hotkeys that diverged
    reached_consensus: bool = False # True if quorum + threshold met
    avg_verification_time_ms: float = 0.0


@dataclass
class ValidatorState:
    """Per-validator reliability tracking."""
    hotkey: str
    total_validations: int = 0
    agreements: int = 0
    divergences: int = 0
    recent_results: deque = field(default_factory=lambda: deque(maxlen=DIVERGENCE_WINDOW))
    reliability_score: float = 1.0
    slashed: bool = False
    slash_count: int = 0
    avg_verification_time_ms: float = 0.0
    total_proofs_verified: int = 0

    def update(self, agreed: bool, verification_time_ms: int = 0) -> None:
        """Update reliability after a consensus round."""
        self.total_validations += 1
        self.recent_results.append(agreed)
        if agreed:
            self.agreements += 1
        else:
            self.divergences += 1

        # EMA for verification time
        if verification_time_ms > 0:
            self.total_proofs_verified += 1
            alpha = 0.1
            self.avg_verification_time_ms = (
                alpha * verification_time_ms + (1 - alpha) * self.avg_verification_time_ms
            )

        self._recompute_reliability()

    def _recompute_reliability(self) -> None:
        if self.total_validations == 0:
            self.reliability_score = 1.0
            return

        lifetime_rate = self.agreements / self.total_validations
        recent_agrees = sum(1 for r in self.recent_results if r)
        recent_rate = recent_agrees / len(self.recent_results) if self.recent_results else 1.0

        self.reliability_score = 0.6 * lifetime_rate + 0.4 * recent_rate

        if len(self.recent_results) >= DIVERGENCE_WINDOW:
            divergence_rate = 1.0 - recent_rate
            if divergence_rate > SLASH_THRESHOLD and not self.slashed:
                self.slashed = True
                self.slash_count += 1
                logger.warning(
                    "Validator %s slashed (divergence=%.2f, count=%d)",
                    self.hotkey, divergence_rate, self.slash_count,
                )


class ConsensusEngine:
    """Manages multi-validator consensus for proof verification."""

    def __init__(self) -> None:
        self._validators: dict[str, ValidatorState] = {}
        self._pending_votes: dict[str, list[VerificationVote]] = {}  # "job_id:part_idx" → votes

    def get_or_create_validator(self, hotkey: str) -> ValidatorState:
        if hotkey not in self._validators:
            self._validators[hotkey] = ValidatorState(hotkey=hotkey)
        return self._validators[hotkey]

    def assign_verifiers(
        self,
        job_id: str,
        available_validators: list[str],
        stakes: dict[str, float] | None = None,
    ) -> list[str]:
        """Select validators for proof verification, weighted by reliability and stake."""
        import random

        if len(available_validators) <= MAX_VALIDATORS_PER_PROOF:
            return available_validators

        stake_map = stakes or {}
        weights = []
        for hotkey in available_validators:
            state = self.get_or_create_validator(hotkey)
            if state.slashed:
                weights.append(0.0)
            else:
                reliability = max(state.reliability_score, 0.01)
                stake_w = 1.0 + min(stake_map.get(hotkey, 0.0) / 1000.0, 1.0)
                weights.append(reliability * stake_w)

        total = sum(weights)
        if total == 0:
            return random.sample(available_validators, min(MAX_VALIDATORS_PER_PROOF, len(available_validators)))

        selected = set()
        attempts = 0
        while len(selected) < MAX_VALIDATORS_PER_PROOF and attempts < 100:
            idx = random.choices(range(len(available_validators)), weights=weights, k=1)[0]
            selected.add(available_validators[idx])
            attempts += 1

        return list(selected)

    def submit_vote(self, vote: VerificationVote) -> None:
        """Submit a proof verification vote from a validator."""
        key = f"{vote.job_id}:{vote.partition_index}"
        self._pending_votes.setdefault(key, [])
        for existing in self._pending_votes[key]:
            if existing.validator_hotkey == vote.validator_hotkey:
                logger.warning("Duplicate vote from %s for %s", vote.validator_hotkey, key)
                return
        self._pending_votes[key].append(vote)

    def compute_consensus(
        self, job_id: str, partition_index: int,
        stakes: dict[str, float] | None = None,
    ) -> ProofConsensusResult | None:
        """Compute binary consensus from pending verification votes.

        For ZK proofs, the question is simple: valid or invalid?
        The majority (stake-weighted) determines the answer.
        """
        key = f"{job_id}:{partition_index}"
        votes = self._pending_votes.get(key, [])
        if len(votes) < MIN_QUORUM:
            return None

        stake_map = stakes or {}

        # Count stake-weighted valid/invalid votes
        valid_stake = 0.0
        invalid_stake = 0.0
        total_stake = 0.0
        total_verif_time = 0
        for vote in votes:
            v_stake = max(stake_map.get(vote.validator_hotkey, 1.0), 1.0)
            total_stake += v_stake
            total_verif_time += vote.verification_time_ms
            if vote.valid:
                valid_stake += v_stake
            else:
                invalid_stake += v_stake

        # Majority wins
        consensus_valid = valid_stake >= invalid_stake
        majority_stake = valid_stake if consensus_valid else invalid_stake
        agreement_ratio = majority_stake / total_stake if total_stake > 0 else 0.0
        reached = agreement_ratio >= CONSENSUS_THRESHOLD

        # Determine agreeing/diverging validators
        agreeing = []
        diverging = []
        for vote in votes:
            if vote.valid == consensus_valid:
                agreeing.append(vote.validator_hotkey)
            else:
                diverging.append(vote.validator_hotkey)

        # Update validator reliability
        for vote in votes:
            state = self.get_or_create_validator(vote.validator_hotkey)
            state.update(
                agreed=(vote.valid == consensus_valid),
                verification_time_ms=vote.verification_time_ms,
            )

        avg_time = total_verif_time / len(votes) if votes else 0.0

        result = ProofConsensusResult(
            job_id=job_id,
            partition_index=partition_index,
            consensus_valid=consensus_valid if reached else False,
            agreement_ratio=agreement_ratio,
            quorum_size=len(votes),
            agreeing_validators=agreeing,
            diverging_validators=diverging,
            reached_consensus=reached,
            avg_verification_time_ms=avg_time,
        )

        self._pending_votes.pop(key, None)
        return result

    def get_validator_state(self, hotkey: str) -> ValidatorState | None:
        return self._validators.get(hotkey)

    def get_all_validators(self) -> list[ValidatorState]:
        return list(self._validators.values())
