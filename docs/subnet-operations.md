# Subnet Operations Runbook

Operational guide for running ZKML miners and validators on the Bittensor subnet.

---

## Architecture Overview

The ZKML subnet consists of:

- **Validators** — receive proof requests, dispatch them to miners, verify results, and update consensus scores.
- **Miners** — GPU-equipped nodes that execute ZK proof generation.
- **Consensus Engine** — stake-weighted binary voting to determine proof validity.
- **Anti-Sybil Layer** — GPU benchmark verification, rate limiting, proof hash deduplication, stake gates.

---

## Starting a Validator

### Prerequisites

- Bittensor wallet with sufficient stake
- Python 3.10+
- Redis (for distributed rate limiting)

### Launch

```bash
# Set environment
export BT_NETUID=<subnet-id>
export BT_WALLET_NAME=default
export BT_HOTKEY=default

# Run validator
python -m subnet.neurons.validator \
    --netuid $BT_NETUID \
    --wallet.name $BT_WALLET_NAME \
    --wallet.hotkey $BT_HOTKEY \
    --subtensor.network finney
```

### Validator Configuration

| Setting                        | Default | Description                                   |
| ------------------------------ | ------- | --------------------------------------------- |
| `epoch_length`                 | 100     | Steps per scoring epoch (~20 min at 12s/step) |
| `dispatch_interval`            | 30s     | How often to check for queued jobs            |
| `benchmark_challenge_interval` | 3600s   | How often to re-verify miners                 |

---

## Starting a Miner

### Prerequisites

- NVIDIA GPU with CUDA support (or ROCm/Metal)
- Sufficient VRAM for target proof systems
- Bittensor wallet

### Launch

```bash
python -m subnet.neurons.miner \
    --netuid $BT_NETUID \
    --wallet.name $BT_WALLET_NAME \
    --wallet.hotkey $BT_HOTKEY \
    --gpu_backend cuda
```

### GPU Requirements by Proof System

| Proof System | Min VRAM | Recommended |
| ------------ | -------- | ----------- |
| Groth16      | 4 GB     | 8 GB        |
| PLONK        | 8 GB     | 16 GB       |
| Halo2        | 8 GB     | 16 GB       |
| STARK        | 16 GB    | 24 GB       |

---

## Consensus Engine Parameters

| Parameter                    | Value | Description                            |
| ---------------------------- | ----- | -------------------------------------- |
| `MIN_QUORUM`                 | 2     | Minimum validators for consensus       |
| `CONSENSUS_THRESHOLD`        | 0.66  | 66% stake-weighted agreement           |
| `MAX_VALIDATORS_PER_PROOF`   | 5     | Max validators assigned per proof      |
| `DIVERGENCE_WINDOW`          | 50    | Rolling window for reliability scoring |
| `SLASH_THRESHOLD`            | 0.20  | Slash at >20% divergence               |
| `VALIDATOR_EVICTION_SECONDS` | 3600  | Evict inactive validators after 1h     |

---

## Anti-Sybil Gates

### Stake Gate

Rejects miners whose TAO stake is below `min_stake_to_publish` (configurable in settings).

### GPU Benchmark Gate

Requires `benchmark_score >= 1.0` (default). CPU-only nodes are rejected from proof dispatch.

### Benchmark Verifier (PoW)

Validators periodically send 1K-constraint test circuits to miners. The miner must prove within tolerance:

- `actual_score >= claimed_score * 0.3`
- Results cached for 1 hour
- Untrusted miners are deprioritized in dispatch

### Rate Limiter

- 50 requests per hotkey per epoch (1 hour)
- Sliding window with in-memory tracking

### Proof Hash Deduplicator

Prevents miners from reusing proof fragments across jobs. Maintains last 10,000 hashes.

---

## Monitoring

### Key Metrics

- **Validator reliability scores** — via `engine.get_stats()`
- **Slashed validator count** — `engine.get_slashed_validators()`
- **Pending vote sets** — indicates consensus latency
- **Circuit breaker state** — Redis keys `cb:open:{webhook_id}`

### Health Checks

```bash
# Registry API health
curl http://localhost:8000/health

# Network stats
zkml network-stats

# Prover status
zkml provers --online
```

### Grafana Dashboard

Import `grafana/dashboard.json` for pre-built views of:

- Proof throughput and latency
- Prover online/offline counts
- Job queue depth
- Error rates

---

## Troubleshooting

### Miner Not Receiving Jobs

1. Check the miner is registered: `zkml provers --online`
2. Verify benchmark score meets minimum: `benchmark_score >= 1.0`
3. Confirm GPU is detected: check `gpu_name` in prover registration
4. Ensure the miner's hotkey has sufficient stake

### Validator Slashed

1. Check slash reason: `engine.get_slashed_validators()`
2. Divergence rate exceeds 20% over the last 50 validations
3. Recovery: validator must achieve reliability >= 0.85 over a full window
4. Manual un-slash: `engine.try_unslash(hotkey, min_reliability=0.85)`

### Proof Job Stuck in DISPATCHED

1. Check partition status: `zkml proof-status <task_id>`
2. Assigned prover may be offline — job times out after `soft_time_limit` (300s)
3. Celery worker may be down — check `celery -A registry.tasks.celery_app status`

### High Consensus Latency

1. Check pending vote count in `engine.get_stats()`
2. Insufficient validators online — need >= `MIN_QUORUM` (2) for consensus
3. Stale votes are cleaned up after 10 minutes automatically

---

## Upgrading

### Rolling Upgrade

1. Upgrade validators first — they're backward-compatible with older miners
2. Upgrade miners incrementally
3. Run `alembic upgrade head` for database migrations before deploying new registry code

### Database Migrations

```bash
# Check current revision
alembic current

# Preview pending migrations
alembic history --verbose

# Apply
alembic upgrade head
```

---

## Emergency Procedures

### Circuit Breaker Tripped on Webhooks

```bash
# Check Redis for open circuit breakers
redis-cli keys "cb:open:*"

# Clear a specific breaker
redis-cli del cb:open:<webhook_id> cb:failures:<webhook_id>
```

### Mass Slashing Event

```bash
# List all slashed validators
python -c "
from subnet.consensus.engine import ConsensusEngine
engine = ConsensusEngine()
# Load state from your persistence layer
for v in engine.get_slashed_validators():
    print(v.hotkey, v.reliability_score, v.slash_count)
"
```

### Celery Queue Backup

```bash
# Check queue length
celery -A registry.tasks.celery_app inspect active
celery -A registry.tasks.celery_app inspect reserved

# Purge stuck tasks (use with caution)
celery -A registry.tasks.celery_app purge
```
