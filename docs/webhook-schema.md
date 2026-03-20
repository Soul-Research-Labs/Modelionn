# Webhook Event Schema

ZKML delivers events to your HTTPS endpoints via POST with JSON payloads signed using HMAC-SHA256.

---

## Delivery Format

Every webhook delivery wraps the event data in a standard envelope:

```json
{
  "event": "proof.completed",
  "timestamp": "2025-01-15T10:30:00.000Z",
  "webhook_id": 42,
  "data": { ... }
}
```

### HTTP Headers

| Header                  | Description                                                                   |
| ----------------------- | ----------------------------------------------------------------------------- |
| `Content-Type`          | `application/json`                                                            |
| `X-ZKML-Signature` | `sha256=<hex-digest>` — HMAC-SHA256 of the raw body using your webhook secret |
| `X-ZKML-Event`     | Event type string (e.g. `proof.completed`)                                    |

### Verifying Signatures

Compute HMAC-SHA256 of the raw request body using your webhook secret and compare:

```python
import hmac, hashlib

def verify(body: bytes, secret: str, signature_header: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
```

---

## Event Types

### `proof.completed`

Fired when a proof job finishes successfully.

```json
{
  "event": "proof.completed",
  "data": {
    "job_id": 123,
    "task_id": "abc-def-456",
    "circuit_id": 10,
    "circuit_name": "my-circuit",
    "proof_hash": "a1b2c3...64hex",
    "proof_data_cid": "QmXyz...",
    "proof_type": "groth16",
    "generation_time_ms": 4200,
    "num_partitions": 4
  }
}
```

### `proof.failed`

Fired when a proof job fails after exhausting retries.

```json
{
  "event": "proof.failed",
  "data": {
    "job_id": 124,
    "task_id": "abc-def-789",
    "circuit_id": 10,
    "error": "No online provers available",
    "status": "failed"
  }
}
```

### `proof.dispatched`

Fired when a proof job is dispatched to provers.

```json
{
  "event": "proof.dispatched",
  "data": {
    "job_id": 125,
    "task_id": "abc-def-101",
    "circuit_id": 10,
    "circuit_name": "my-circuit",
    "num_partitions": 4,
    "provers_assigned": 3
  }
}
```

### `circuit.uploaded`

Fired when a new circuit is published to the registry.

```json
{
  "event": "circuit.uploaded",
  "data": {
    "circuit_id": 11,
    "name": "new-circuit",
    "version": "1.0.0",
    "proof_type": "plonk",
    "num_constraints": 50000,
    "publisher_hotkey": "5Abc..."
  }
}
```

### `prover.online`

Fired when a prover registers or comes back online.

```json
{
  "event": "prover.online",
  "data": {
    "hotkey": "5Xyz...",
    "gpu_name": "NVIDIA RTX 4090",
    "gpu_backend": "cuda",
    "benchmark_score": 42.5,
    "vram_total_bytes": 25769803776
  }
}
```

### `prover.offline`

Fired when a prover fails to heartbeat within the eviction window.

```json
{
  "event": "prover.offline",
  "data": {
    "hotkey": "5Xyz...",
    "last_seen": "2025-01-15T10:00:00.000Z"
  }
}
```

---

## Managing Webhooks

### CLI

```bash
# Create
zkml webhooks create \
    --url https://example.com/hook \
    --label "Production" \
    --events "proof.completed,proof.failed"

# List
zkml webhooks list

# Update
zkml webhooks update 42 --active

# Delete
zkml webhooks delete 42
```

### API

```
POST   /webhooks          Create webhook
GET    /webhooks          List webhooks
PATCH  /webhooks/{id}     Update webhook
DELETE /webhooks/{id}     Delete webhook
```

---

## Reliability

### Retry Policy

Failed deliveries are retried up to **3 times** with exponential backoff (10s, 20s, 40s, max 60s).

### Circuit Breaker

After **5 consecutive failures**, the webhook is automatically disabled and logged to the dead-letter queue (DLQ). The circuit breaker opens for 5 minutes.

- Distributed state is stored in Redis (`cb:failures:{id}`, `cb:open:{id}`)
- Falls back to in-process tracking if Redis is unavailable

### Dead-Letter Queue

Permanently failed deliveries are logged to `zkml.webhook.dlq` at ERROR level. Operators can replay them by parsing the DLQ log entries.

### Timeouts

Each delivery attempt has a **10-second timeout**. Ensure your endpoint responds within this window.

---

## Filtering Events

Use the `events` field when creating a webhook:

| Value                          | Description                       |
| ------------------------------ | --------------------------------- |
| `*`                            | All events                        |
| `proof.completed`              | Only completed proofs             |
| `proof.completed,proof.failed` | Multiple events (comma-separated) |
| `circuit.uploaded`             | Only circuit uploads              |

Allowed event types: `*`, `proof.completed`, `proof.failed`, `proof.dispatched`, `circuit.uploaded`, `prover.online`, `prover.offline`.
