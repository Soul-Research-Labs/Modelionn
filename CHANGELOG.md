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
- **IDOR fixed**: `list_proof_jobs` no longer accepts `?requester=` param to view other users' jobs
- **Scoped queries**: `list_proofs` now filters by caller's hotkey instead of returning all proofs
- **Soft-delete filters**: Circuit queries exclude soft-deleted records (`deleted_at IS NULL`)
- **CSP nonce-based styles**: Replaced `style-src 'unsafe-inline'` with nonce-based injection
- **FLOWER_PASSWORD required**: Production entrypoint validates Flower password at startup

### Added

- **Commit-reveal anti-frontrunning** — Validators commit proof hashes before revealing to prevent score manipulation
- **ConsensusEngine** — Multi-validator binary proof verification with stake-weighted voting (66% threshold, min quorum 2, max 5 validators)
- **Validator reliability tracking** — 60% lifetime + 40% recent (50-vote window) with slashing for >20% divergence
- **Job cancellation** — `DELETE /proofs/jobs/{task_id}` cancels QUEUED/DISPATCHED jobs
- **Job deduplication** — Prevents duplicate proof jobs for the same (circuit_id, witness_cid, requester) combo
- **Circuit race protection** — `FOR UPDATE` lock prevents concurrent name+version duplicates
- **Webhook configuration** — CRUD API (`/webhooks`) + settings UI; HTTPS-only URLs, HMAC secrets, max 10 per user
- **Miner load shedding** — Rejects proof requests when `_current_load >= 1.0`; 600s proof generation timeout
- **SDK improvements** — Exponential backoff with jitter, `cancel_proof_job()`, 408 retry, auth headers on all requests
- **CLI commands** — `cancel-proof`, `get-proof`, `list-proofs` added to CLI
- **Alertmanager service** — Webhook-based alert routing with severity groups (critical/warning)
- **Automated backups** — Daily PostgreSQL backup cron service at 02:00 UTC with 7-day retention
- **Rate limit headers** — `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` on every response
- **Per-circuit job limit** — Max 50 concurrent proof jobs per circuit to prevent DoS
- `asyncpg>=0.29` added to project dependencies (required for prod PostgreSQL)

### Added (Documentation)

- **SECURITY.md** — Comprehensive threat model, authentication flows, hardening guide
- **docs/disaster-recovery.md** — RTO/RPO targets, failover procedures, recovery validation checklist
- **docs/capacity-planning.md** — Resource sizing for small/medium/large deployments
- **docs/tls-setup.md** — TLS/HTTPS setup with Nginx and Caddy, HSTS, OCSP stapling
- **docs/monitoring-setup.md** — Prometheus, Grafana, Alertmanager configuration guide
- **.env.prod.example** — Aligned with all config variables (database, IPFS, Redis, Celery, Bittensor, Sentry, backup)

### Added (Tests)

- 39 middleware + reward + anti-Sybil tests
- 15 validator integration tests (commit-reveal, consensus verification, scoring)
- 8 consensus e2e tests (multi-round, slashing, stake-weighted overrule, partition isolation)
- 28 miner neuron integration tests (load shedding, CID validation, blacklist, priority, verification, state)
- 32 SDK integration tests (proof lifecycle, retry, auth, orgs, API keys, connection management)
- Locust load tests with 3 user profiles (ReadOnly, ProofRequester, Admin)
- **Total: 361 tests passing**

### Fixed

- Fix `registry.core.database` import errors (module doesn't exist) —
  use `registry.core.deps.async_session` across all Celery tasks
- Fix `download_bytes()` AttributeError — add alias in `StorageBackend` base class
- Fix `UploadResult` type mismatch in `proof_aggregate.py` — extract `.cid`
- Fix empty `proof_systems` dict in `/provers/stats` — now aggregates from
  `supported_proof_types_csv` across all provers
- Remove duplicate `refresh_prover_rankings` Celery task (was scheduled at
  both 6h and 30min intervals)
- Fix `test_organizations.py::TestMembership::test_list_members` — missing auth headers
- Fix `test_proof_aggregate.py` (3 tests) — constant/timeout assertion mismatches

### Changed

- Version bumped to 0.2.0 (aligned pyproject.toml with app.py)
- CONTRIBUTING.md: remove ghost `tests/evaluation/` references
- DEPLOYMENT.md: fix `DATABASE_URL` → `MODELIONN_DATABASE_URL` in troubleshooting
- Web CI now runs Jest in the web pipeline (`npm test -- --runInBand`) in addition to lint and typecheck
- Frontend auth pages now wrap `useSearchParams()` in `Suspense` to satisfy Next.js prerender/build requirements
- Settings UI now aligns with typed API contracts (`ApiKey`/`Webhook`) and uses strongly typed field access
- Frontend lint/type cleanup across dashboard/routes/realtime hooks removes unused imports, empty interfaces, and explicit `any`
- Added `web/.eslintrc.json` for deterministic non-interactive linting in local and CI environments

### Changed (Documentation)

- README operational guides table formatting normalized for readability
- Operational runbooks normalized with trailing newlines for cleaner diffs/tooling consistency

## [Backlog (Pre-0.2)]

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
- **Database**: 10 SQLAlchemy ORM tables, 10 Alembic migrations
- **Tasks**: Celery proof dispatch pipeline, prover health monitoring, periodic maintenance
- **Infra**: Docker Compose (11 services), GPU overlay, production overlay
- **Infra**: Prometheus + Grafana + Alertmanager monitoring
- **Docs**: `DEPLOYMENT.md`, `ARCHITECTURE.md`, `SECURITY.md`, testnet, TLS, monitoring, DR, capacity planning

### Changed

- `alembic.ini` now uses `%(MODELIONN_DATABASE_URL)s` instead of hardcoded SQLite path
