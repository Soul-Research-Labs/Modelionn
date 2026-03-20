# Rollback Procedure Guide

Steps to safely revert the ZKML registry to a previous release.

## Pre-Rollback Checklist

- [ ] Identify the target rollback version tag (e.g., `v0.1.9`).
- [ ] Verify the Alembic migration of the target version (`alembic history`).
- [ ] Take a fresh DB backup: `scripts/backup.sh`
- [ ] Notify stakeholders of the maintenance window.

## Rolling Back the Application

### Docker Compose

```bash
# 1. Stop the current release
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# 2. Checkout the target tag
git checkout v0.1.9

# 3. Rebuild images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 4. Start
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Kubernetes (if applicable)

```bash
kubectl rollout undo deployment/zkml-api --to-revision=<N>
kubectl rollout undo deployment/zkml-worker --to-revision=<N>
kubectl rollout status deployment/zkml-api --timeout=120s
```

## Rolling Back Database Migrations

**This is the most critical step.** Only roll back if the new migration is incompatible with the old code.

```bash
# 1. Identify current head
alembic current

# 2. Downgrade one step
alembic downgrade -1

# 3. Or downgrade to a specific revision
alembic downgrade 0012_add_composite_indexes
```

### Migration Rollback Risks

| Risk                           | Mitigation                                 |
| ------------------------------ | ------------------------------------------ |
| Data loss from dropped columns | Always use `nullable=True` for new columns |
| FK constraint violations       | Check dependent tables before dropping     |
| Index drops under load         | Schedule during low-traffic window         |

## Rolling Back Celery Workers

Celery workers must match the API version to avoid task signature mismatches.

```bash
# Drain existing tasks first
celery -A registry.tasks.celery_app control shutdown

# Then restart with rolled-back code
docker compose up -d worker
```

## Post-Rollback Verification

1. **Health check:** `curl http://localhost:8000/health`
2. **DB consistency:** `alembic current` should match the target revision.
3. **Proof pipeline:** Submit a test proof request and verify it completes.
4. **Monitoring:** Check Grafana dashboards for error rate spikes.

## Emergency Rollback (data corruption)

If the database is corrupted:

```bash
# 1. Stop everything
docker compose down

# 2. Restore from backup
scripts/restore.sh /backups/pg_zkml_<timestamp>.dump

# 3. Downgrade migrations to match backup point
alembic downgrade <revision_at_backup_time>

# 4. Restart with matching code version
git checkout <tag_at_backup_time>
docker compose up -d
```

See [disaster-recovery.md](disaster-recovery.md) for full DR procedures.
