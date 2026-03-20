# Load Tests

Load tests for the ZKML Registry API using [Locust](https://locust.io/).

## Setup

```bash
pip install locust
```

## Run

```bash
# Web UI (interactive)
locust -f tests/load/locustfile.py --host http://localhost:8000

# Headless (CI-friendly)
locust -f tests/load/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  --users 50 \
  --spawn-rate 5 \
  --run-time 60s \
  --csv results

# With authentication (provide hotkey for write endpoints)
ZKML_HOTKEY=5FYourKey ZKML_SIGN_KEY=your-sign-key \
  locust -f tests/load/locustfile.py --host http://localhost:8000
```

## Profiles

The locustfile defines three user types with different traffic patterns:

| User Type        | Weight | Behavior                                             |
| ---------------- | ------ | ---------------------------------------------------- |
| `ReadOnlyUser`   | 5      | Reads circuits, provers, stats — high frequency      |
| `ProofRequester` | 2      | Requests proofs, polls status — medium frequency     |
| `AdminUser`      | 1      | Org management, API keys, audit logs — low frequency |

## Interpreting Results

Key metrics to watch:

- **P95/P99 latency**: Should stay under 500ms for reads, 2s for writes
- **Failure rate**: Should be < 1% under normal load
- **RPS**: Target throughput depends on deployment tier (see `docs/capacity-planning.md`)
