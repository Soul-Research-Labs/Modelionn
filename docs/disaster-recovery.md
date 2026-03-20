# Disaster Recovery Plan — ZKML

## 1. Recovery Objectives

| Metric                             | Target       | Notes                                                    |
| ---------------------------------- | ------------ | -------------------------------------------------------- |
| **RTO** (Recovery Time Objective)  | ≤ 30 minutes | Time from incident detection to full service restoration |
| **RPO** (Recovery Point Objective) | ≤ 24 hours   | Maximum acceptable data loss (aligned with daily backup) |

---

## 2. Backup Strategy

### 2.1 Automated Daily Backups

The `backup` service in `docker-compose.prod.yml` runs daily at **02:00 UTC** using `scripts/backup.sh`.

- **Database**: Full `pg_dump` with custom format (`-Fc`) to `/backups/zkml_YYYYMMDD_HHMMSS.sql`
- **Retention**: 7 days (configurable via `ZKML_BACKUP_RETAIN_DAYS`)
- **Volume**: `backup_data` Docker named volume

### 2.2 Manual Backup

```bash
# Trigger an immediate backup
docker compose -f docker-compose.prod.yml exec backup /scripts/backup.sh

# Verify backup file
docker compose -f docker-compose.prod.yml exec backup ls -lh /backups/
```

### 2.3 Off-Site Backup (Recommended)

Copy backups to an off-site location for geographic redundancy:

```bash
# Example: sync to S3
aws s3 sync /var/lib/docker/volumes/zkml_backup_data/_data/ \
  s3://your-bucket/zkml-backups/ --storage-class STANDARD_IA

# Example: sync to another server
rsync -az /var/lib/docker/volumes/zkml_backup_data/_data/ \
  backup-host:/backups/zkml/
```

---

## 3. Failure Scenarios & Recovery Procedures

### 3.1 Database Failure (PostgreSQL Crash / Corruption)

**Detection**: `CeleryWorkerDown` or `MetricsEndpointDown` Prometheus alert; health check failures on `/health/ready`.

**Recovery**:

```bash
# 1. Stop services
docker compose -f docker-compose.prod.yml stop registry worker beat web

# 2. Restore from latest backup
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U zkml -d zkml --clean --if-exists \
  < /backups/zkml_LATEST.sql

# 3. Run migrations to ensure schema is current
docker compose -f docker-compose.prod.yml exec registry alembic upgrade head

# 4. Restart services
docker compose -f docker-compose.prod.yml up -d registry worker beat web
```

**Estimated recovery time**: 5–15 minutes.

### 3.2 Complete Host Failure

**Recovery**:

```bash
# 1. Provision a new host with Docker 24+

# 2. Clone the repository
git clone <repo-url> && cd ZKML

# 3. Restore environment config
cp .env.prod.example .env
# Fill in all secrets (keep a secure copy of production .env)

# 4. Start infrastructure services first
docker compose -f docker-compose.prod.yml up -d postgres redis ipfs

# 5. Wait for health checks to pass
docker compose -f docker-compose.prod.yml ps

# 6. Restore database from off-site backup
cat /path/to/backup.sql | docker compose -f docker-compose.prod.yml exec -T \
  postgres pg_restore -U zkml -d zkml --clean --if-exists

# 7. Run migrations
docker compose -f docker-compose.prod.yml exec registry alembic upgrade head

# 8. Start remaining services
docker compose -f docker-compose.prod.yml up -d

# 9. Verify
curl https://your-domain.com/health/ready
```

**Estimated recovery time**: 20–30 minutes (depends on data transfer speed).

### 3.3 Redis Failure

Redis is used for caching and Celery broker. Data loss is tolerable — no persistent state.

```bash
docker compose -f docker-compose.prod.yml restart redis
# Workers will auto-reconnect. In-flight Celery tasks may be lost and need re-dispatch.
```

**Estimated recovery time**: 1–2 minutes.

### 3.4 IPFS Node Failure

Circuit artifacts and proof files are content-addressed. If the local IPFS node dies, data can be re-pinned from the IPFS network.

```bash
# 1. Restart IPFS
docker compose -f docker-compose.prod.yml restart ipfs

# 2. If data volume is lost, IPFS will re-sync pinned content from peers
# For critical circuits, keep a local backup of CIDs and re-pin:
docker compose -f docker-compose.prod.yml exec ipfs ipfs pin add <CID>
```

**Estimated recovery time**: 2–5 minutes (longer if re-pinning large datasets).

### 3.5 Application-Level Incident (Bad Deployment)

```bash
# 1. Roll back to the previous image
docker compose -f docker-compose.prod.yml pull  # if using tagged images
# Or: git checkout <last-known-good-commit>

# 2. Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build registry worker web

# 3. If a migration was applied, roll back
docker compose -f docker-compose.prod.yml exec registry alembic downgrade -1
```

---

## 4. Communication & Escalation

| Severity          | Trigger                                                   | Response                               |
| ----------------- | --------------------------------------------------------- | -------------------------------------- |
| **P1 — Critical** | All provers offline, database down, API unreachable       | Immediate: page on-call engineer       |
| **P2 — High**     | Proof queue > 100, P99 latency > 300s, single worker down | Within 15 min: investigate and resolve |
| **P3 — Warning**  | Low prover count, elevated API key rejections             | Within 1 hour: monitor and plan fix    |

Alertmanager is configured to route alerts via webhook. Configure `docker/alertmanager/alertmanager.yml` to send notifications to your preferred channel (Slack, PagerDuty, email).

---

## 5. Recovery Validation Checklist

After any recovery, verify:

- [ ] `/health` returns `200`
- [ ] `/health/ready` returns `200` (database + Redis connected)
- [ ] Prometheus targets are UP (`http://prometheus:9090/targets`)
- [ ] Grafana dashboards show data flow
- [ ] Celery workers are online: `docker compose exec flower celery inspect active`
- [ ] Submit a test proof job and verify completion
- [ ] IPFS gateway responds: `curl http://localhost:8080/ipfs/<known-CID>`

---

## 6. Periodic Drills

| Drill               | Frequency | Procedure                                                           |
| ------------------- | --------- | ------------------------------------------------------------------- |
| Backup restore test | Monthly   | Restore latest backup to a staging database, verify schema and data |
| Failover simulation | Quarterly | Stop primary host, recover on standby using off-site backups        |
| Runbook review      | Quarterly | Review this document and all referenced scripts for accuracy        |
