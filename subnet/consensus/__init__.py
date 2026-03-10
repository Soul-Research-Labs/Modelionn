"""Multi-validator consensus engine."""

from .engine import (
    ConsensusEngine,
    ProofConsensusResult,
    VerificationVote,
    ValidatorState,
)

# Backward-compatible aliases for legacy tests
ConsensusResult = ProofConsensusResult
EvalVote = VerificationVote

__all__ = [
    "ConsensusEngine",
    "ProofConsensusResult",
    "VerificationVote",
    "ValidatorState",
    "ConsensusResult",
    "EvalVote",
]
