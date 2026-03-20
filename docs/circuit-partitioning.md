# Circuit Partitioning Heuristics

How the ZKML proof pipeline splits large circuits into parallelizable partition fragments.

## Overview

When a proof request arrives, the dispatch task divides the circuit's constraint system into `N` partitions, each assigned to a different prover (miner) on the network.

```
Circuit (131,072 constraints)
  ├── Partition 0: constraints [0, 32768)    → Prover A
  ├── Partition 1: constraints [32768, 65536) → Prover B
  ├── Partition 2: constraints [65536, 98304) → Prover C
  └── Partition 3: constraints [98304, 131072) → Prover A (redundancy)
```

## Partitioning Algorithm

```python
max_per = settings.max_constraints_per_partition  # default: 32768
num_partitions = ceil(circuit.num_constraints / max_per)
num_partitions = min(num_partitions, settings.max_partitions_per_job)
constraints_per = ceil(circuit.num_constraints / num_partitions)
```

### Configuration

| Setting                         | Default | Description                  |
| ------------------------------- | ------- | ---------------------------- |
| `max_constraints_per_partition` | `32768` | Max constraints per fragment |
| `max_partitions_per_job`        | `256`   | Hard cap on partition count  |

## Prover Assignment

Partitions are assigned to online provers using **load-aware weighted selection**:

```
effective_weight = benchmark_score × (1 - current_load × 0.8)
```

This prevents overloading slower or busier provers. The assignment uses deterministic hashing (`_pick_weighted_index`) for reproducibility.

### Redundancy

Each partition can be assigned to `redundancy` provers (default: 2). The system avoids assigning the same partition to the same prover twice.

### Anti-Sybil Gates

Before assignment, provers pass through:

1. **GPU Benchmark Gate** — minimum benchmark score threshold
2. **Stake Gate** — minimum TAO stake requirement (checked at consensus level)

## Commitment Hash Validation

Each `CircuitPartitionRow` has a `commitment_hash` field (SHA-256) that the prover must include in its proof fragment response. This prevents fragment substitution attacks.

```
commitment_hash = SHA256(circuit_hash || partition_index || constraint_start || constraint_end)
```

## Fragment Completion

When a partition completes:

1. Prover submits the proof fragment CID via the subnet protocol.
2. The validator verifies the fragment against the commitment hash.
3. `CircuitPartitionRow.status` transitions: `pending → assigned → proving → completed`.
4. When all partitions complete, `proof_aggregate` combines fragments.

## Performance Considerations

| Circuit Size      | Partitions | Typical Time | GPU Recommendation |
| ----------------- | ---------- | ------------ | ------------------ |
| < 32K constraints | 1          | < 10s        | Any GPU            |
| 32K - 256K        | 2-8        | 10-60s       | RTX 3080+          |
| 256K - 1M         | 8-32       | 1-5m         | RTX 4090 / A100    |
| > 1M constraints  | 32-256     | 5-30m        | Multi-GPU cluster  |

## Tuning

- **Small circuits** (<32K): Set `max_constraints_per_partition` high to avoid unnecessary overhead from partitioning.
- **ZKML circuits**: Often have dense constraint matrices; lower the partition size for better parallelism.
- **High redundancy**: Increase `redundancy` for mission-critical proofs (2-3x recommended).

## Failure Handling

If a partition fails:

- The job status transitions to `FAILED`.
- Error details are recorded in `CircuitPartitionRow.error`.
- Webhook event `proof.failed` fires.
- No automatic retry at the partition level (retry at job level via Celery).
