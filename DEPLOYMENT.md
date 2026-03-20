# Deployment Guide

## Prerequisites

- Docker 24+ with Compose v2
- 4 GB RAM minimum (8 GB recommended)
- PostgreSQL 16 (production) or SQLite (development)

## Quick Start (Development)

```bash
# Clone & start all services
git clone https://github.com/zkml/zkml.git
cd zkml
docker compose up -d --build

# Verify
curl http://localhost:8000/health
open http://localhost:3000
```

## Production Deployment

### 1. Environment Configuration

Copy the example env file and configure all required values:

```bash
cp .env.prod.example .env
```

Required variables:

| Variable               | Description                                                             |
| ---------------------- | ----------------------------------------------------------------------- |
| `POSTGRES_PASSWORD`    | PostgreSQL database password                                            |
| `ZKML_SECRET_KEY` | API signing secret (min 32 chars, generate with `openssl rand -hex 32`) |
| `NEXTAUTH_SECRET`      | NextAuth session signing secret                                         |
| `CORS_ORIGINS`         | Allowed frontend origins (e.g. `https://app.zkml.io`)              |
| `FLOWER_PASSWORD`      | Celery Flower admin password                                            |

### 2. Start Services

Run the preflight validator to catch missing secrets and compose issues early:

```bash
./scripts/deploy_preflight.sh .env
# or
make deploy-preflight
```

Then start services:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 3. Run Database Migrations

```bash
docker compose exec registry alembic upgrade head
```

### 4. Verify Health

```bash
curl -sf http://localhost:8000/health | jq
curl -sf http://localhost:8000/health/ready | jq
```

## Service Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend   │────▶│   Registry  │────▶│  PostgreSQL  │
│  (Next.js)   │     │  (FastAPI)  │     │             │
│  :3000       │     │  :8000      │     │  :5432      │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │             │
               ┌────▼────┐  ┌────▼────┐
               │  Redis   │  │   IPFS  │
               │  :6379   │  │  :5001  │
               └────┬────┘  └─────────┘
                    │
               ┌────▼────┐  ┌──────────┐
               │ Worker   │  │ Flower   │
               │ (Celery) │  │  :5555   │
               └─────────┘  └──────────┘
```

## Monitoring

- **Prometheus**: http://localhost:9090 — metrics scraping
- **Grafana**: http://localhost:3001 — dashboards (default password: `admin`)
- **Flower**: http://localhost:5555 — Celery task monitoring (prod: behind auth)

## Backups

```bash
# Create backup
./scripts/backup.sh ./backups

# Restore PostgreSQL
./scripts/restore.sh pg backups/pg_20260315_120000.dump

# Restore SQLite
./scripts/restore.sh sqlite backups/sqlite_20260315_120000.db
```

Backups auto-prune after 7 days.

## Scaling

```bash
# Scale Celery workers
docker compose up -d --scale worker=4

# Scale with load balancer (add nginx/traefik)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale registry=3
```

## HTTPS (TLS)

For production, run behind a reverse proxy (Nginx, Caddy, or Traefik) with TLS termination:

```nginx
server {
    listen 443 ssl;
    server_name api.zkml.io;

    ssl_certificate /etc/letsencrypt/live/api.zkml.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.zkml.io/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## IPFS Node Security

The IPFS Kubo API (port **5001**) grants full read/write access to the node — including pinning, garbage collection, and configuration changes. **Never expose port 5001 to the public internet.**

### Firewall Rules

```bash
# Allow IPFS API only from localhost and the Docker bridge network
sudo ufw deny 5001
sudo ufw allow from 172.16.0.0/12 to any port 5001  # Docker internal
sudo ufw allow from 127.0.0.1 to any port 5001

# The IPFS gateway (port 8080) is read-only and safe to expose if needed
# sudo ufw allow 8080
```

### Docker Compose

The default `docker-compose.yml` already binds IPFS API to `127.0.0.1:5001` (localhost only). Verify this is _not_ changed to `0.0.0.0:5001` in production overrides:

```yaml
# CORRECT — internal only
ipfs:
  ports:
    - "127.0.0.1:5001:5001" # API — internal only
    - "8080:8080" # Gateway — read-only, safe to expose


# WRONG — exposes writable API to the internet
# ipfs:
#   ports:
#     - "5001:5001"
```

### Additional Recommendations

- **IPFS_API_URL** should always point to a private address (`http://ipfs:5001` inside Docker, or `http://127.0.0.1:5001` on the host).
- Enable IPFS API authentication if running Kubo ≥ 0.25 (see [Kubo docs](https://docs.ipfs.tech/reference/kubo-rpc-cli/)).
- Review `Access-Control-Allow-Origin` in IPFS config — restrict to known origins.
- Pin only content uploaded through the registry; run periodic `ipfs repo gc` to reclaim storage from unpinned objects.

## Troubleshooting

| Symptom                            | Fix                                                                        |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `RuntimeError: Default secret key` | Set `ZKML_SECRET_KEY` env var (min 32 chars)                          |
| `DATABASE_URL must be set`         | Set `ZKML_DATABASE_URL` in `.env` — entrypoint validates before start |
| Redis connection refused           | Check Redis container is healthy: `docker compose ps redis`                |
| IPFS timeouts                      | Increase `ZKML_IPFS_TIMEOUT` or check IPFS node                       |
| 403 on webhook endpoints           | Ensure user has org membership via `/orgs/{slug}/members`                  |
| 429 Too Many Requests              | Rate limit: 120 req/60s per client — check `Retry-After` header            |
| CSRF validation failed             | `Origin` header must match server host, or use `Authorization: Bearer`     |
| Worker tasks stuck                 | Check Flower UI, restart workers with `docker compose restart worker`      |

## Operational Runbooks

- [Environment Setup](docs/environment-setup.md)
- [Database Migration](docs/database-migration.md)
- [Celery Operations](docs/celery-operations.md)
- [IPFS Operations](docs/ipfs-operations.md)
- [Alert Runbooks](docs/alert-runbooks.md)
- [Proof Job Diagnostics](docs/proof-job-diagnostics.md)
- [Encryption Key Management](docs/encryption-key-management.md)
