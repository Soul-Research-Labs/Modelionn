# Modelionn — GPU-Accelerated ZK Prover Network

> **Distributed zero-knowledge proof generation powered by [Bittensor](https://bittensor.com/).**

Modelionn is a decentralised ZK prover network where GPU miners collaborate to generate
zero-knowledge proofs. Circuits and witnesses are content-addressed on IPFS, proof jobs are
partitioned and dispatched across GPU-equipped miners, and a Bittensor subnet rewards fast,
correct, and reliable proof generation with TAO.

**Why Modelionn?**

- **Multi-proof-system** — Groth16, PLONK, Halo2, and STARKs in a single network.
- **GPU-accelerated** — Rust prover engine with CUDA, ROCm, Metal, and WebGPU backends.
- **Distributed proving** — Large circuits are partitioned and proven collaboratively across miners.
- **Incentives** — A Bittensor subnet rewards correctness, speed, throughput, and reliability with TAO.
- **General-purpose** — Supports general, EVM, zkML, and custom circuit types.

## Architecture

```
┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐
│ Next.js  │──▶│   Registry   │──▶│     IPFS     │   │   Redis   │
│ Dashboard│   │  (FastAPI)   │   │ (circuits +  │   │  (cache)  │
└──────────┘   └──────┬───────┘   │   proofs)    │   └─────┬─────┘
                      │           └──────────────┘         │
               ┌──────▼───────┐                     ┌───────▼─────┐
               │  Bittensor   │                     │   Celery    │
               │   Subnet     │                     │  (dispatch) │
               │  val → miner │                     └─────────────┘
               └──────┬───────┘
                      │
               ┌──────▼───────┐
               │  Rust Prover │  ← GPU-accelerated (CUDA/ROCm/Metal/WebGPU)
               │   Engine     │
               └──────────────┘
┌──────────┐   ┌──────────────┐
│ CLI/SDK  │──▶│   Registry   │  (same service — Python client)
│ (Python) │   │              │
└──────────┘   └──────────────┘
```

| Layer        | Purpose                                                             |
| ------------ | ------------------------------------------------------------------- |
| **Prover**   | Rust engine — Groth16/PLONK/Halo2/STARK with GPU acceleration       |
| **Registry** | FastAPI service — circuit CRUD, proof jobs, prover management, RBAC |
| **Storage**  | IPFS — content-addressed circuits, witnesses, and proof fragments   |
| **Subnet**   | Bittensor neurons — validators dispatch, miners prove, TAO rewards  |
| **Dispatch** | Celery pipeline — partition circuits, assign to GPU miners          |
| **Web**      | Next.js 14 dashboard — prover network, circuits, proof jobs         |
| **SDK**      | Python client — `client.upload_circuit()`, `client.request_proof()` |
| **CLI**      | Terminal tool — `modelionn prove`, `modelionn circuits`, etc.       |

## Features

### ZK Prover Network

- **Multi-proof-system support** — Groth16 (BN254), PLONK, Halo2, and STARKs (Winterfell)
- **GPU acceleration** — CUDA (NVIDIA), ROCm (AMD), Metal (Apple), WebGPU backends via Rust engine
- **Circuit partitioning** — Large circuits split into partitions, proven in parallel across miners
- **Redundant proving** — Configurable redundancy factor for fault tolerance
- **Cross-verification** — Validators send proof fragments to different miners for verification
- **Circuit types** — General-purpose, EVM-compatible, zkML, and custom circuits
- **IPFS storage** — Circuits, witnesses, verification keys, and proofs are content-addressed

### Bittensor Subnet

- **Proof dispatch** — Validators partition circuits and assign GPU miners based on capabilities
- **Capability discovery** — `CapabilityPingSynapse` reports GPU info, benchmarks, and load
- **Binary consensus** — ZK proofs are valid/invalid; stake-weighted majority determines correctness
- **Prover scoring** — Correctness (0.35), Speed (0.30), Throughput (0.20), Reliability (0.10), Efficiency (0.05)
- **Anti-Sybil** — Stake gate, rate limiter, GPU benchmark gate, proof hash deduplication

### Platform

- **Security hardening** — HSTS, CSP (nonce-based), X-Frame-Options, AES-256-GCM field encryption, request-ID tracing
- **Multi-tenancy & RBAC** — Organisations, memberships, role-based access (Viewer / Editor / Admin)
- **Immutable audit trail** — Every mutation logged with actor, action, resource, and timestamp
- **Redis-backed rate limiting** — Sliding-window algorithm with in-memory fallback
- **Redis nonce replay protection** — `SET NX` with TTL for cryptographic nonces
- **IPFS retry logic** — Tenacity-based retry with exponential backoff on transient failures
- **Timing-safe API key comparison** — `hmac.compare_digest` prevents side-channel attacks
- **CSRF middleware** — Origin validation on state-changing requests; Bearer tokens exempt
- **Thread-safe metrics** — `threading.Lock` on in-flight request counter
- **Streaming audit export** — Async generator avoids buffering large CSV exports
- **IPFS content verification** — Hash check after upload to detect corruption
- **Celery task hardening** — `asyncio.run()`, idempotency keys, Sentry DLQ alerts
- **Fail-fast secret validation** — Runtime error on default secrets in production
- **Non-root Docker** — Hardened Dockerfile with dedicated user and healthcheck
- **Connection pooling** — Persistent `httpx.Client` in SDK with configurable pool limits
- **Commit-reveal anti-frontrunning** — Prevents score frontrunning between validators
- **Webhook configuration** — CRUD API + settings UI for event-driven integrations (HTTPS-enforced)
- **Job cancellation** — Cancel QUEUED/DISPATCHED proof jobs via `DELETE /proofs/jobs/{task_id}`
- **Job deduplication** — Prevents duplicate proof jobs for the same circuit + witness
- **Miner load shedding** — Rejects requests when at capacity; 600s proof timeout
- **Automated backups** — Daily PostgreSQL backups at 02:00 UTC with 7-day retention
- **Alertmanager** — Prometheus alert routing to Slack, PagerDuty, or webhook receivers

### Web Dashboard

- Next.js 14 App Router + TypeScript + Tailwind CSS
- 4 main routes: Dashboard, Prover Network, Circuits, Proof Jobs
- @tanstack/react-query for data fetching, Zustand for client state
- Wallet-based authentication via NextAuth
- Full accessibility: skip links, ARIA labels, semantic HTML, keyboard navigation

## Quick Start

```bash
# Install the registry + SDK + CLI in dev mode
pip install -e ".[dev]"

# Build the Rust prover engine (requires Rust toolchain)
cd prover && cargo build --release && cd ..
# Or with GPU support: cargo build --release --features cuda

# Start the API server
uvicorn registry.api.app:app --reload

# Upload a circuit
modelionn upload-circuit --name my-circuit --proof-type groth16 --circuit-type general \
  --constraints 100000 --cid QmXxx...

# Request a proof
modelionn prove <circuit-id> --witness QmYyy... --partitions 4 --redundancy 2

# Check proof status
modelionn proof-status <task-id>

# List network provers
modelionn provers --online

# Network statistics
modelionn network-stats

# Launch the web dashboard
cd web && npm install && npm run dev
```

Or spin up the full stack with Docker Compose:

```bash
cp .env.example .env
docker compose up -d        # registry, redis, worker, flower, ipfs, web, prometheus, grafana, beat
curl http://localhost:8000/health
open http://localhost:3000   # Dashboard
```

For GPU-accelerated proving with NVIDIA GPUs:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

For production deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

Operational runbooks:

- [docs/environment-setup.md](docs/environment-setup.md)
- [docs/database-migration.md](docs/database-migration.md)
- [docs/celery-operations.md](docs/celery-operations.md)
- [docs/ipfs-operations.md](docs/ipfs-operations.md)
- [docs/alert-runbooks.md](docs/alert-runbooks.md)
- [docs/proof-job-diagnostics.md](docs/proof-job-diagnostics.md)
- [docs/encryption-key-management.md](docs/encryption-key-management.md)

## API Endpoints

### ZK Prover Network

| Method   | Path                                | Description                       |
| -------- | ----------------------------------- | --------------------------------- |
| POST/GET | `/circuits`                         | Upload and list circuits          |
| GET      | `/circuits/{id}`                    | Get circuit details               |
| GET      | `/circuits/by-hash/{hash}`          | Lookup circuit by content hash    |
| GET      | `/circuits/{id}/download`           | Download circuit from IPFS        |
| POST     | `/proofs/request`                   | Request a new proof job           |
| GET      | `/proofs/jobs`                      | List proof jobs                   |
| GET      | `/proofs/jobs/{task_id}`            | Get proof job status + partitions |
| GET      | `/proofs/jobs/{task_id}/partitions` | Get partition details             |
| DELETE   | `/proofs/jobs/{task_id}`            | Cancel a queued/dispatched job    |
| GET      | `/proofs`                           | List completed proofs             |
| POST     | `/proofs/{id}/verify`               | Verify a proof                    |
| POST/GET | `/provers`                          | Register and list provers         |
| GET      | `/provers/{hotkey}`                 | Get prover details by hotkey      |
| GET      | `/provers/{hotkey}/stats`           | Get prover statistics             |
| POST     | `/provers/{hotkey}/ping`            | Report prover health/capabilities |

### Organizations, RBAC & Webhooks

| Method   | Path                   | Description               |
| -------- | ---------------------- | ------------------------- |
| POST/GET | `/orgs`                | Organization CRUD         |
| POST/GET | `/orgs/{slug}/members` | Membership management     |
| GET      | `/audit`               | Query immutable audit log |
| GET      | `/audit/export`        | Stream audit CSV          |
| GET      | `/webhooks`            | List webhook configs      |
| POST     | `/webhooks`            | Create webhook config     |
| PUT      | `/webhooks/{id}`       | Update webhook config     |
| DELETE   | `/webhooks/{id}`       | Delete webhook config     |

### API Keys

| Method | Path             | Description    |
| ------ | ---------------- | -------------- |
| POST   | `/api-keys`      | Create API key |
| GET    | `/api-keys`      | List API keys  |
| DELETE | `/api-keys/{id}` | Revoke API key |

### Infrastructure

| Method | Path            | Description                   |
| ------ | --------------- | ----------------------------- |
| GET    | `/health`       | Health check                  |
| GET    | `/health/ready` | Readiness (DB + Redis)        |
| GET    | `/metrics`      | Prometheus‑compatible metrics |

All requests include `X-Request-ID` header. Rate limit: 120 req/60s per client.

## Bittensor Subnet

The subnet incentivises GPU miners to generate ZK proofs:

**Prover Reward Weights:**

| Factor          | Weight | Description                                      |
| --------------- | ------ | ------------------------------------------------ |
| **Correctness** | 0.35   | Fraction of valid proofs generated               |
| **Speed**       | 0.30   | Proof generation time (normalised vs 60s target) |
| **Throughput**  | 0.20   | Proofs completed per epoch                       |
| **Reliability** | 0.10   | Uptime and response success rate                 |
| **Efficiency**  | 0.05   | Proof quality relative to GPU resources used     |

**Synapses:**

| Synapse                 | Direction       | Purpose                                  |
| ----------------------- | --------------- | ---------------------------------------- |
| `ProofRequestSynapse`   | Validator→Miner | Request proof generation for a partition |
| `CapabilityPingSynapse` | Validator→Miner | Discover GPU capabilities + benchmark    |
| `ProofVerifySynapse`    | Validator→Miner | Cross-verify another miner's proof       |

**Anti-Sybil:** Stake gate (≥1.0 TAO), rate limiter (50 req/epoch), GPU benchmark gate, proof hash deduplication.

**Consensus:** Binary valid/invalid votes, stake-weighted majority, 66% agreement threshold, min quorum of 2, max 5 validators per proof.

**Commit-Reveal:** Anti-frontrunning protocol — validators commit proof hashes before revealing, preventing score manipulation.

## Middleware Stack

| Order | Middleware                    | Purpose                                                    |
| ----- | ----------------------------- | ---------------------------------------------------------- |
| 1     | **RequestIDMiddleware**       | Generates `X-Request-ID` (uuid4) for distributed tracing   |
| 2     | **SecurityHeadersMiddleware** | HSTS, CSP (no unsafe-eval), X-Frame-Options, XCTO          |
| 3     | **CSRFMiddleware**            | Origin validation on POST/PUT/PATCH/DELETE; Bearer exempt  |
| 4     | **TenantMiddleware**          | Resolves `X-Org-Slug` header to organisation context       |
| 5     | **RateLimitMiddleware**       | Redis sliding-window (120 req/60s) with in-memory fallback |
| 6     | **MetricsMiddleware**         | HTTP request count, latency histogram, in-flight gauge     |

## CI / CD

CI runs on every push and PR:

1. **Lint** — ruff check
2. **Type check** — mypy
3. **Test** — pytest with coverage upload to Codecov
4. **Frontend test** — Jest suite for dashboard pages/components
5. **Security scan** — Bandit (SAST), pip-audit (CVE scan), npm audit
6. **Alembic** — Migration chain integrity check
7. **Docker** — Compose build verification (all branches)

### Publishing to PyPI

Creating a GitHub Release triggers the `publish.yml` workflow, which builds and
publishes the package via OIDC trusted publishing (no API token required).

## Monitoring & Observability

- **Prometheus** — `/metrics` endpoint exposes counters, gauges, and histograms
  (HTTP request rate, latency, in-flight, proofs generated, provers online).
- **Grafana** — Import `grafana/dashboard.json` for a pre-built dashboard.
- **Alertmanager** — 13 alert rules for provers, proofs, IPFS, API keys, nonce replays, Celery workers.
- **Sentry** — Set `SENTRY_DSN` env var to enable error tracking and tracing.
- **Audit Export** — `GET /audit/export` returns CSV for compliance/analysis.

See [docs/monitoring-setup.md](docs/monitoring-setup.md) for detailed setup instructions.

## Load Testing

```bash
pip install locust
locust -f tests/load/locustfile.py --host http://localhost:8000
# Open http://localhost:8089 — 3 user profiles: ReadOnly, ProofRequester, Admin
```

See [tests/load/README.md](tests/load/README.md) for headless mode and CI integration.

## Testnet Deployment

See [docs/testnet-deployment.md](docs/testnet-deployment.md) for step-by-step
instructions on wallet creation, registration, and running miner/validator neurons.

## Operational Guides

| Guide                                                  | Description                                   |
| ------------------------------------------------------ | --------------------------------------------- |
| [DEPLOYMENT.md](DEPLOYMENT.md)                         | Production deployment with Docker Compose     |
| [SECURITY.md](SECURITY.md)                             | Threat model, authentication flows, hardening |
| [docs/tls-setup.md](docs/tls-setup.md)                 | TLS/HTTPS with Nginx or Caddy                 |
| [docs/monitoring-setup.md](docs/monitoring-setup.md)   | Prometheus, Grafana, Alertmanager setup       |
| [docs/disaster-recovery.md](docs/disaster-recovery.md) | RTO/RPO targets, failover procedures          |
| [docs/capacity-planning.md](docs/capacity-planning.md) | Resource sizing by workload tier              |

## Development

```bash
pip install -e ".[dev]"

# Fast tests (no Redis/Celery/Docker required)
make test-fast

# Full suite
make test

# Lint + type check
make lint
make typecheck
```

## Docker Compose Services

| Service      | Image              | Port      | Purpose                               |
| ------------ | ------------------ | --------- | ------------------------------------- |
| registry     | ./Dockerfile       | 8000      | FastAPI API server                    |
| redis        | redis:7-alpine     | 6379      | Cache + Celery broker                 |
| worker       | ./Dockerfile       | —         | Celery workers (proof dispatch queue) |
| beat         | ./Dockerfile       | —         | Celery Beat periodic tasks            |
| flower       | ./Dockerfile       | 5555      | Celery monitoring UI                  |
| ipfs         | ipfs/kubo          | 5001/8080 | Circuit + proof storage               |
| web          | ./web/Dockerfile   | 3000      | Next.js ZK dashboard                  |
| prometheus   | prom/prometheus    | 9090      | Metrics collection                    |
| grafana      | grafana/grafana    | 3001      | Monitoring dashboards                 |
| alertmanager | prom/alertmanager  | 9093      | Alert routing (Slack/PagerDuty/email) |
| backup       | postgres:16-alpine | —         | Daily pg_dump (prod only, 02:00 UTC)  |

```bash
docker compose up -d
docker compose logs -f registry
```

## Project Structure

```
├── prover/             # Rust GPU prover engine (PyO3)
│   ├── src/            # Backends (Groth16/PLONK/Halo2/STARK), GPU (CUDA/ROCm/Metal/WebGPU)
│   └── python/         # Python wrapper with Rust or fallback
├── registry/           # FastAPI service (core)
│   ├── api/            # Routes (circuits, proofs, provers, orgs, audit, api-keys, metrics) + middleware
│   ├── core/           # Config, deps, encryption, cache, security
│   ├── models/         # SQLAlchemy 2.0 ORM (10 tables) + Pydantic v2 schemas
│   ├── storage/        # IPFS adapter (tenacity retry + content verification)
│   └── tasks/          # Celery proof dispatch, prover health, periodic tasks
├── subnet/             # Bittensor subnet neurons
│   ├── neurons/        # Miner (GPU prover) + Validator (proof dispatcher)
│   ├── consensus/      # Binary proof verification consensus engine
│   ├── protocol/       # Synapses (ProofRequest, CapabilityPing, ProofVerify)
│   └── reward/         # Prover scoring + anti-sybil (stake, benchmark, dedup)
├── sdk/                # Python client library (py.typed)
├── cli/                # Terminal interface (Typer + Rich)
├── web/                # Next.js 14 dashboard
├── alembic/            # Database migrations (10 revisions)
├── grafana/            # Grafana dashboard JSON + provisioning
├── docker/             # Neuron Dockerfiles, entrypoint, alertmanager config
├── scripts/            # Registration, backup/restore
├── docs/               # Operational guides (TLS, DR, capacity, monitoring, testnet)
├── tests/              # 361 tests across all layers + Locust load tests
├── docker-compose.yml  # Development deployment (9 services)
└── docker-compose.prod.yml  # Production deployment (with secrets)
```

## License

MIT — see [LICENSE](LICENSE) for details.
