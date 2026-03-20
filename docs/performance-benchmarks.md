# Performance Benchmarks

This guide captures a baseline method for benchmarking proof pipeline latency.

## Goal

Measure end-to-end latency from proof job submission to terminal state for a fixed circuit and witness.

## Prerequisites

- Registry API running (local or staging)
- At least one uploaded circuit and valid witness CID
- Optional auth headers if signature verification is enabled

## Benchmark Command

```bash
python3 scripts/benchmark_proof_pipeline.py \
  --base-url http://localhost:8000 \
  --circuit-id 1 \
  --witness-cid QmYourWitnessCid \
  --jobs 10 \
  --poll-interval 1.0 \
  --timeout 300
```

If authenticated endpoints are required:

```bash
ZKML_HOTKEY=5F... ZKML_SIGNATURE=your-signature \
python3 scripts/benchmark_proof_pipeline.py --circuit-id 1 --witness-cid QmYourWitnessCid
```

## Reported Metrics

- jobs_total
- jobs_completed
- jobs_failed
- latency_avg_s
- latency_p50_s
- latency_p95_s
- latency_p99_s

## Baseline Capture Template

Record each benchmark run with environment details:

- Date:
- Git SHA:
- Environment: local | staging | production
- Proof type:
- Circuit constraints:
- Jobs:
- Latency avg/p50/p95/p99:
- Failure rate:

## Recommended SLO Tracking

Use these as initial targets and tighten over time:

- p95 latency under 10s for small/medium circuits
- failure rate below 1% under steady load
- no regression greater than 10% versus last accepted baseline
