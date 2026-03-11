# Changelog

All notable changes to Modelionn are documented in this file.

## [0.2.0] — Unreleased

### Security

- **Auth bypass closed**: Circuits, proofs, and provers endpoints now require
  authenticated headers (x-hotkey/x-signature/x-nonce) via `verify_publisher`
  dependency instead of accepting unauthenticated `?hotkey=` query params
- **CSRF hardened**: Reject state-changing requests without Origin/Referer header;
  exempt Bittensor wallet auth and Bearer tokens
- **Request-ID validation**: Reject arbitrary X-Request-ID values; only accept
  hex UUID strings (max 36 chars) to prevent log injection
- **Redis auth in prod**: Require `REDIS_PASSWORD` for all Redis connections
- **IPFS API restricted**: Remove port 5001 exposure in production compose
- **Grafana anonymous access disabled** in production overlay
- **Resource limits** added for registry, worker, and beat services
- **Secret validation**: Entrypoint now validates `MODELIONN_SECRET_KEY` in prod
- **Cargo.lock required**: Dockerfile uses strict COPY for reproducible Rust builds

### Fixed

- Fix `registry.core.database` import errors (module doesn't exist) —
  use `registry.core.deps.async_session` across all Celery tasks
- Fix `download_bytes()` AttributeError — add alias in `StorageBackend` base class
- Fix `UploadResult` type mismatch in `proof_aggregate.py` — extract `.cid`
- Fix empty `proof_systems` dict in `/provers/stats` — now aggregates from
  `supported_proof_types_csv` across all provers
- Remove duplicate `refresh_prover_rankings` Celery task (was scheduled at
  both 6h and 30min intervals)

### Added

- `asyncpg>=0.29` added to project dependencies (required for prod PostgreSQL)
- 39 new tests: middleware (CSRF, request-ID, rate limit, security headers,
  tenant), reward scoring, and anti-Sybil mechanisms

### Changed

- Version bumped to 0.2.0 (aligned pyproject.toml with app.py)
- CONTRIBUTING.md: remove ghost `tests/evaluation/` references
- DEPLOYMENT.md: fix `DATABASE_URL` → `MODELIONN_DATABASE_URL` in troubleshooting

## [Unreleased]

### Added

- **ZK Prover Network** — GPU-accelerated distributed proof generation on Bittensor
  - Multi-proof-system support: Groth16, PLONK, Halo2, STARK
  - Rust prover engine with CUDA, Metal, ROCm, WebGPU backends (PyO3 bindings)
  - Circuit partitioning for parallel proving across GPU miners
  - Configurable redundancy factor for fault tolerance
  - Cross-verification: validators send proof fragments to different miners
  - Circuit types: general, EVM, zkML, custom
- **Bittensor Subnet** — Proof dispatch and incentive layer
  - Validators partition circuits and dispatch to GPU miners
  - `CapabilityPingSynapse` for GPU capability discovery
  - Binary consensus engine with stake-weighted voting (66% threshold)
  - Prover scoring: correctness (0.35), speed (0.30), throughput (0.20), reliability (0.10), efficiency (0.05)
  - Anti-Sybil: stake gate, rate limiter, GPU benchmark gate, proof hash deduplication
- **Security**: Timing-safe API key comparison via `hmac.compare_digest`
- **Security**: CSRF middleware — origin validation on state-changing requests; Bearer tokens exempt
- **Security**: Secure `X-Forwarded-For` parsing (first hop only)
- **Security**: Thread-safe in-flight request counter with `threading.Lock`
- **Security**: Redis-backed sliding window rate limiter with in-memory fallback
- **Security**: Redis-backed nonce replay prevention with TTL
- **Security**: Fail-fast `RuntimeError` if default secret key used in production
- **Security**: Non-root Docker user (`modelionn`) with health check
- **Security**: Removed `unsafe-eval` from Content Security Policy
- **Security**: SAST (Bandit) and dependency scanning in CI pipeline
- **Reliability**: Streaming audit CSV export via async generator
- **Reliability**: IPFS content verification — hash check after upload
- **Reliability**: Celery task hardening — `asyncio.run()`, idempotency keys
- **Frontend**: Next.js 14 dashboard — Dashboard, Prover Network, Circuits, Proof Jobs
- **Frontend**: 30s request timeout with `AbortController`
- **Frontend**: 429 rate-limit handling with `Retry-After` header parsing
- **Frontend**: Toast notification system with auto-dismiss
- **Frontend**: Wallet authentication via NextAuth
- **Frontend**: Accessibility — skip links, ARIA labels, semantic HTML, keyboard navigation
- **SDK**: Python client with connection pooling, retry with backoff, typed ZK methods
- **CLI**: `modelionn circuits`, `upload-circuit`, `prove`, `proof-status`, `proof-jobs`, `verify-proof`
- **CLI**: `modelionn provers`, `network-stats`, `info`, `auth`, `login`
- **CLI**: `--json` flag for machine-readable output, config file support (`~/.modelionn.toml`)
- **Registry**: FastAPI service with 7 route modules (circuits, proofs, provers, orgs, audit, api-keys, metrics)
- **Registry**: 7-layer middleware stack (RequestID, SecurityHeaders, CSRF, Tenant, APIKeyAuth, RateLimit, Metrics)
- **Registry**: Multi-tenancy & RBAC (Viewer / Editor / Admin)
- **Registry**: Immutable audit trail with CSV export
- **Registry**: Prometheus-compatible `/metrics` endpoint
- **Registry**: IPFS storage with tenacity retry and content verification
- **Database**: 10 SQLAlchemy ORM tables, 4 Alembic migrations
- **Tasks**: Celery proof dispatch pipeline, prover health monitoring, periodic maintenance
- **Infra**: Docker Compose (9 services), GPU overlay, production overlay
- **Infra**: Prometheus + Grafana monitoring
- **Docs**: `DEPLOYMENT.md`, `ARCHITECTURE.md`, testnet deployment guide

### Changed

- `alembic.ini` now uses `%(MODELIONN_DATABASE_URL)s` instead of hardcoded SQLite path
