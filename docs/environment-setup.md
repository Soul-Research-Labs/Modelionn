# Environment Setup Runbook

Use this checklist before every production deploy.

## 1. Create Env File

```bash
cp .env.prod.example .env
```

## 2. Validate Required Secrets

```bash
grep -E '^(POSTGRES_PASSWORD|ZKML_SECRET_KEY|ZKML_ENCRYPTION_KEY|NEXTAUTH_SECRET|FLOWER_PASSWORD)=' .env
```

Validation rules:

- `ZKML_SECRET_KEY`: 64 hex chars recommended.
- `ZKML_ENCRYPTION_KEY`: Fernet key, base64-encoded 32-byte key.
- `NEXTAUTH_SECRET`: at least 32 random bytes.
- `POSTGRES_PASSWORD`: high-entropy passphrase, no placeholder values.

## 3. Confirm Cross-Service Consistency

The following values must match for `registry`, `worker`, and `beat`:

- `ZKML_DATABASE_URL`
- `ZKML_SECRET_KEY`
- `ZKML_REDIS_URL`
- `ZKML_ENCRYPTION_KEY`

Quick check:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /tmp/zkml.compose.rendered.yml
rg "ZKML_(DATABASE_URL|SECRET_KEY|REDIS_URL|ENCRYPTION_KEY)" /tmp/zkml.compose.rendered.yml
```

## 4. Preflight Checks

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
```

## 5. Post-Deploy Health Checks

```bash
curl -sf http://localhost:8000/health | jq
curl -sf http://localhost:8000/health/ready | jq
curl -sf http://localhost:8000/metrics | head -20
```

If readiness fails, stop rollout and use [database-migration.md](database-migration.md) and [celery-operations.md](celery-operations.md) for recovery.
