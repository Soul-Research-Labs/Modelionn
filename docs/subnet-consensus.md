# Subnet Consensus & Voting Rules

How validation, rewards, and consensus work on the ZKML Bittensor subnet.

## Architecture

```
Validators                    Miners (Provers)
    │                              │
    ├── ProofRequestSynapse ──────→│  (forward proof work)
    │                              │
    │←── ProofFragment ───────────│  (return computed proof)
    │                              │
    ├── Score & Vote ──────→ Yuma Consensus
    │                              │
    └── Set Weights ──────→ Bittensor Chain
```

## Scoring Criteria

Each validator scores miners on four axes with configurable weights:

| Criterion         | Weight | Description                                              |
| ----------------- | ------ | -------------------------------------------------------- |
| `proof_quality`   | 0.40   | Proof correctness, verification time, fragment integrity |
| `speed_score`     | 0.25   | Actual proof time vs. estimated time                     |
| `availability`    | 0.20   | `uptime_ratio` × response rate                           |
| `stake_alignment` | 0.15   | Higher stake = more skin in the game                     |

### Composite Score

```python
score = (
    weights["proof_quality"] * quality +
    weights["speed_score"] * speed +
    weights["availability"] * availability +
    weights["stake_alignment"] * stake_factor
)
```

## Anti-Sybil Gates

Before a miner can receive work, it must pass:

### GPU Benchmark Gate

- Minimum benchmark score threshold.
- Prevents CPU-only nodes from bidding on GPU work.
- Configured via `ConsensusEngine` initialization.

### Stake Gate

- Minimum TAO stake requirement.
- Evaluated at the consensus layer during weight-setting.

## Consensus Engine

The `ConsensusEngine` class (`subnet/consensus/engine.py`) orchestrates:

1. **Score Matrix**: Maintains `validator × miner` score matrix.
2. **Weight Setting**: Periodically calls `subtensor.set_weights()` on-chain.
3. **EMA Smoothing**: Exponential moving average over scoring epochs to reduce volatility.

### Configuration

| Setting               | Default         | Description                         |
| --------------------- | --------------- | ----------------------------------- |
| `scoring_weights`     | See table above | Criterion weights (must sum to 1.0) |
| `min_benchmark_score` | `10.0`          | GPU benchmark gate threshold        |
| `ema_alpha`           | `0.1`           | EMA smoothing factor                |
| `weight_set_interval` | `100` (blocks)  | How often validators set weights    |

## Reward Distribution

Rewards flow through Bittensor's native mechanism:

1. Validators set weights on the metagraph.
2. Yuma Consensus aggregates weights across all validators.
3. Miners receive TAO proportional to their weighted rank.

### Reward Penalties

- **Failed proofs**: Zero score for the epoch.
- **Slow responses**: Linearly decreasing `speed_score` based on timeout ratio.
- **Offline**: `availability = 0` when prover is not reachable.
- **Sybil detection**: Duplicate hotkeys or colluding validators flagged via weight analysis.

## Validator Responsibilities

| Task                   | Frequency        | Code Path                               |
| ---------------------- | ---------------- | --------------------------------------- |
| Forward proof requests | On demand        | `subnet/neurons/validator.py:forward()` |
| Score proof responses  | Per response     | `subnet/reward/scoring.py`              |
| Set on-chain weights   | Every 100 blocks | `ConsensusEngine.set_weights()`         |
| Monitor miner health   | Every 60s        | `registry/tasks/prover_health.py`       |

## Miner Responsibilities

| Task                  | Frequency       | Code Path                                           |
| --------------------- | --------------- | --------------------------------------------------- |
| Handle proof requests | On demand       | `subnet/neurons/miner.py:handle_proof_request()`    |
| Report capabilities   | On registration | `subnet/base/miner_base.py:register_capabilities()` |
| Heartbeat pings       | Every 30s       | Miner axon → Validator                              |

## Troubleshooting

| Issue                         | Diagnosis                                                   | Resolution                                |
| ----------------------------- | ----------------------------------------------------------- | ----------------------------------------- |
| Miner receives no work        | Check `benchmark_score` and `online` status                 | Ensure GPU benchmark passes the gate      |
| Low rewards                   | Check `uptime_ratio` and `successful_proofs / total_proofs` | Improve hardware reliability              |
| Validator not setting weights | Check `subtensor` connection and wallet permissions         | Verify coldkey/hotkey registration        |
| Score discrepancies           | Enable debug logging in `ConsensusEngine`                   | Compare local scores vs. on-chain weights |
