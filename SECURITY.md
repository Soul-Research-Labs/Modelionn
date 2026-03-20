# Security Policy — ZKML

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it **privately** via email:

**security@zkml.io**

Do NOT open a public GitHub issue for security-sensitive bugs. We will acknowledge receipt within 48 hours and provide a timeline for a fix.

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Affected component (Registry API, Subnet, Prover, Frontend, SDK)
- Impact assessment (data exposure, privilege escalation, DoS, etc.)

---

## Threat Model

### Trust Boundaries

```
┌────────────────────────────────────────────────────────────┐
│                     Public Internet                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │  Web UI  │  │   SDK    │  │  CLI     │                 │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                 │
│       └──────────────┼─────────────┘                       │
│                      │ HTTPS                               │
├──────────────────────┼─────────────────────────────────────┤
│                ┌─────▼──────┐      Middleware Stack         │
│                │ Registry   │      (7 layers)              │
│                │ API        │─────────────────────┐         │
│                └─────┬──────┘                     │         │
│                      │                            │         │
│            ┌─────────┼──────────┐        ┌────────▼───┐     │
│            │         │          │        │ Celery     │     │
│         ┌──▼──┐  ┌───▼──┐  ┌───▼──┐     │ Workers    │     │
│         │ PG  │  │Redis │  │ IPFS │     └────────────┘     │
│         └─────┘  └──────┘  └──────┘                        │
│                                                            │
│            ┌─────────────────────────────┐                  │
│            │      Bittensor Subnet       │                  │
│            │  Validators ↔ Miners        │                  │
│            │  (axon/dendrite via libp2p) │                  │
│            └─────────────────────────────┘                  │
└────────────────────────────────────────────────────────────┘
```

### Assumed Adversary Capabilities

| Threat Actor        | Capabilities                                       |
| ------------------- | -------------------------------------------------- |
| External attacker   | HTTP requests, network scanning                    |
| Malicious miner     | Submits invalid proofs, front-runs circuit uploads |
| Malicious validator | Submits biased votes, attempts weight manipulation |
| Compromised API key | Authenticated API access within daily limits       |

---

## Authentication & Authorization

### Identity Model

All identities are Bittensor wallets (Ed25519 keypairs). Authentication works via:

1. **Hotkey signature verification** — Every API request includes `X-Hotkey` and `X-Signature` headers. The signature covers the request body (or timestamp for GET requests). Signatures are verified against the Bittensor metagraph.

2. **API key authentication** — For programmatic access. Keys are SHA-256 hashed before storage. Each key has a daily request limit and optional expiration.

3. **Nonce-based replay protection** — Timestamps in signatures are validated to be within a 5-minute window.

### Organization RBAC

| Role     | Permissions                                       |
| -------- | ------------------------------------------------- |
| `viewer` | Read org circuits, proofs, members                |
| `editor` | Upload circuits, request proofs                   |
| `admin`  | Manage members, change settings, delete resources |

Membership is enforced at the route level via `require_org_role()`.

---

## Security Controls

### Middleware Stack (Applied in Order)

| Layer                        | Purpose                                         |
| ---------------------------- | ----------------------------------------------- |
| `RequestIDMiddleware`        | Attach unique request ID for tracing            |
| `SecurityHeadersMiddleware`  | CSP, HSTS, X-Frame-Options, referrer policy     |
| `TenantMiddleware`           | Resolve org tenant from path                    |
| `APIKeyAuthMiddleware`       | Validate API key if present                     |
| `RequestSizeLimitMiddleware` | Reject payloads > 50 MB                         |
| `RateLimitMiddleware`        | Per-IP + per-hotkey rate limiting               |
| `CSRFMiddleware`             | Validate CSRF token for state-changing requests |

### Rate Limiting

- **Per-IP**: 60 requests/minute for unauthenticated, 200/minute for authenticated
- **Per-hotkey**: 200 requests/minute
- **Headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- **Per-user job limit**: Max 10 concurrent proof jobs

### Content Security Policy

```
default-src 'self';
script-src 'self';
style-src 'self' 'nonce-{random}';
img-src 'self' data:;
connect-src 'self' {API_URL};
frame-ancestors 'none';
form-action 'self';
```

Nonce-based style injection replaces `unsafe-inline`.

### Data Protection

- **Encryption at rest**: Database credentials via environment variables, API keys hashed with SHA-256
- **Encryption in transit**: TLS required in production (HSTS enabled)
- **Webhook secrets**: HMAC-SHA256 signing for webhook payloads
- **Soft delete**: Circuits support soft delete (`deleted_at` column) to prevent data loss

---

## Subnet Security

### Anti-Frontrunning (Commit-Reveal)

Circuit submissions use a two-phase commit-reveal protocol:

1. **Commit**: Miner submits `SHA256(name || circuit_hash || nonce)` — recorded by validator
2. **Reveal**: Miner reveals `(name, circuit_hash, nonce)` — validator verifies hash match

The earliest commit for each artifact gets priority, preventing front-running.

### Multi-Validator Consensus

Proof verification uses a binary stake-weighted consensus:

- Verifiers assigned by `ConsensusEngine.assign_verifiers()` (reliability + stake weighted)
- Minimum quorum: 2 validators, max 5 per proof
- Consensus threshold: 66% stake-weighted agreement
- Validator reliability tracked via rolling 50-vote window
- Validators slashed if divergence rate > 20%

### Anti-Sybil Gates

| Gate                    | Purpose                                      |
| ----------------------- | -------------------------------------------- |
| `StakeGate`             | Minimum TAO stake required to participate    |
| `RateLimiter`           | Per-miner proof request rate limiting        |
| `GpuBenchmarkGate`      | Minimum GPU benchmark score to accept proofs |
| `ProofHashDeduplicator` | Reject duplicate proof submissions           |

### Miner Protections

- **Load shedding**: Miners reject proof requests when load ≥ 1.0
- **Timeout enforcement**: Proof generation wrapped with async timeout to prevent hangs
- **Resource limits**: Docker resource constraints (CPU, memory) in production compose

---

## Infrastructure Hardening

### Production Deployment

- All services run as non-root in Docker containers
- Internal services (Redis, IPFS API, Flower) not exposed publicly
- PostgreSQL requires password authentication (`POSTGRES_PASSWORD`)
- Redis requires password (`REDIS_PASSWORD`)
- Flower requires basic auth (`FLOWER_PASSWORD`)
- Resource limits on all services via Docker deploy constraints

### Monitoring & Alerting

- Prometheus scrapes `/metrics` every 10s
- Alert rules: proof timeout spikes, dispatch failures, no online provers, high API key rejections
- Alertmanager routes alerts via webhook with severity-based routing
- Grafana dashboards for operational visibility

### Backups

- Automated daily backups at 02:00 UTC (PostgreSQL, Redis, SQLite)
- Backup retention: 7 days (configurable)
- SHA-256 checksums generated for all backup files
- Restore procedure documented in `scripts/restore.sh`

---

## Hardening Checklist for Operators

- [ ] Set all required secrets: `ZKML_SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `FLOWER_PASSWORD`, `NEXTAUTH_SECRET`
- [ ] Configure `ZKML_CORS_ORIGINS` to your domain only
- [ ] Enable `ZKML_REQUIRE_SIGNATURE_VERIFICATION=true`
- [ ] Set up TLS termination via reverse proxy (Nginx/Caddy) with HSTS
- [ ] Review and customize Prometheus alert thresholds in `docker/prometheus/alerts.yml`
- [ ] Configure alertmanager webhook URL (`ALERTMANAGER_WEBHOOK_URL`) for notifications
- [ ] Restrict Flower, Prometheus, Grafana access to internal network or VPN
- [ ] Run `pip-audit` and `npm audit` regularly for dependency vulnerabilities
- [ ] Enable PostgreSQL WAL archiving for point-in-time recovery
- [ ] Set API key expiration (`expires_in_days`) for all programmatic keys
- [ ] Monitor audit logs (`/audit` endpoint) for anomalous activity

---

## Dependency Scanning

The CI pipeline includes:

- **Python**: `pip-audit` for known CVEs, `bandit` for SAST
- **JavaScript**: `npm audit --audit-level=moderate`
- **Rust**: `cargo clippy` for lint, `cargo audit` recommended
- **Docker**: Build verification with health checks

---

## Incident Response

1. **Detection**: Prometheus alerts trigger webhook notification
2. **Triage**: Check audit logs and Grafana dashboards
3. **Containment**: Revoke compromised API keys, disable affected webhooks
4. **Recovery**: Restore from backup if data integrity compromised
5. **Post-mortem**: Document in incident log, update security controls
