# Architecture

## Overview

Modelionn is a GPU-accelerated ZK prover network built on Bittensor. It combines decentralised storage (IPFS), cryptographic identity (Bittensor wallets), a Rust GPU prover engine, and a Bittensor subnet that rewards fast, correct, and reliable zero-knowledge proof generation with TAO.

## Design Principles

- **Content-addressed storage** — Every circuit, witness, and proof is pinned on IPFS. The CID _is_ the version.
- **Cryptographic identity** — All operations are authenticated via Bittensor wallet signatures.
- **Incentive alignment** — A custom subnet pays TAO for correctness, speed, throughput, and reliability.
- **Defence in depth** — Seven middleware layers, CSRF, rate limiting, and audit logging.

## System Layers

```
                    ┌──────────────────────────────────┐
                    │         Frontend (Next.js)        │
                    │    React • TypeScript • Tailwind  │
                    └──────────────┬───────────────────┘
                                   │ HTTP
                    ┌──────────────▼───────────────────┐
                    │        Registry API (FastAPI)      │
                    │  Routes • Middleware • Deps        │
                    ├───────────────────────────────────┤
                    │           Core Layer               │
                    │  Auth • Security • Config • Cache  │
                    ├───────────────────────────────────┤
                    │         Storage Layer              │
                    │  IPFS Adapter • SQLAlchemy ORM     │
                    └──────────────┬───────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
        ┌─────▼─────┐      ┌──────▼──────┐      ┌──────▼──────┐
        │ PostgreSQL │      │    Redis    │      │    IPFS     │
        │  (metadata)│      │ (cache/mq) │      │  (blobs)    │
        └───────────┘      └─────────────┘      └─────────────┘
```

## Backend (`registry/`)

### API Layer (`registry/api/`)

- **`app.py`** — FastAPI application factory, router registration, middleware stack
- **`routes/`** — 7 route modules: circuits, proofs, provers, organizations, audit, api_keys, metrics
- **`middleware/`** — Request processing pipeline (7 layers):
  - `request_id.py` — Unique request ID propagation (`X-Request-ID`)
  - `security_headers.py` — CSP, HSTS, X-Frame-Options, X-Content-Type-Options
  - `csrf.py` — Origin validation on state-changing methods; Bearer tokens exempt
  - `tenant.py` — Multi-tenant org isolation via `X-Org-Slug`
  - `api_key_auth.py` — Timing-safe API key validation (`hmac.compare_digest`)
  - `rate_limit.py` — Sliding window rate limiter (Redis + in-memory fallback)
  - `metrics.py` — Prometheus counters/histograms (thread-safe in-flight gauge)

### Core (`registry/core/`)

- **`security.py`** — Bittensor wallet authentication: signature verification, nonce replay prevention (Redis-backed), timing-safe comparisons
- **`config.py`** — Pydantic settings with env var binding. Fail-fast on default secrets in production.
- **`cache.py`** — Redis caching layer with graceful fallback
- **`encryption.py`** — AES-256-GCM field encryption for sensitive data

### Models (`registry/models/`)

- **`database.py`** — 10 SQLAlchemy ORM tables: Organizations, Users, Memberships, AuditLogs, APIKeys, Circuits, ProofJobs, CircuitPartitions, Proofs, ProverCapabilities
- **`audit.py`** — Audit trail helper (`log_audit()`)

### Tasks (`registry/tasks/`)

- **`celery_app.py`** — Celery configuration with Redis broker (result TTL: 1h)
- **`proof_dispatch.py`** — Distributed proof pipeline (partition → dispatch → prove → aggregate → verify)
- **`prover_health.py`** — Prover health monitoring, ranking updates, stale job cleanup
- **`periodic.py`** — Scheduled maintenance (API key counter reset, prover ranking refresh)

## Frontend (`web/`)

Next.js 14 App Router with:

- **Pages**: Dashboard, Prover Network, Circuits, Proof Jobs + auth pages
- **Auth**: NextAuth with Bittensor wallet credentials provider
- **Data**: React Query for caching + Zustand for client state
- **UI**: Radix UI primitives + Tailwind CSS + custom design system

## SDK (`sdk/`)

Python SDK with connection pooling, automatic retry with backoff, and typed methods for all ZK API operations (circuits, proofs, provers, network stats).

## CLI (`cli/`)

Typer-based CLI with Rich output:

- `modelionn circuits` — List available circuits
- `modelionn upload-circuit` — Upload a circuit to the registry
- `modelionn prove` — Request a proof job
- `modelionn proof-status` — Check proof job status
- `modelionn proof-jobs` — List proof jobs
- `modelionn verify-proof` — Verify a proof
- `modelionn provers` — List network provers
- `modelionn network-stats` — Show network statistics
- `modelionn info` — Registry health check
- `modelionn login` — Save config to `~/.modelionn.toml`
- `modelionn auth` — Show current authentication status
- `--json` flag for machine-readable output

## Subnet (`subnet/`)

Bittensor subnet integration:

- **Validators**: Dispatch proof jobs to miners, cross-verify proof fragments, binary consensus, set weights
- **Miners**: Accept proof requests, generate ZK proofs with GPU prover engine, report capabilities
- **Consensus**: Binary valid/invalid voting, stake-weighted majority, 66% threshold, min quorum of 2
- **Reward**: 35% correctness + 30% speed + 20% throughput + 10% reliability + 5% efficiency
- **Anti-Sybil**: Stake gate, rate limiter, GPU benchmark gate, proof hash deduplication

## Rust Prover Engine (`prover/`)

GPU-accelerated proof generation with PyO3 Python bindings:

- **Backends**: Groth16 (ark-bn254), PLONK (ark-poly), Halo2 (halo2_proofs), STARK (Winterfell)
- **GPU**: CUDA (ICICLE), Metal, ROCm, WebGPU
- **Partitioning**: Large circuits split into partitions for parallel proving
- **Aggregation**: Proof fragments combined into single proof per system

## Authentication Flow

1. User signs message with Bittensor wallet (SS58 hotkey + nonce + signature)
2. Backend verifies signature against hotkey public key
3. Nonce replay prevention via Redis SET NX with TTL
4. Organization membership checked for scoped operations
5. API keys available for programmatic access (daily rate limits)

## Multi-Tenancy

All resources scoped to organizations. Users have memberships with roles (Viewer, Editor, Admin). RBAC enforced at route level via `require_org_member()`.
