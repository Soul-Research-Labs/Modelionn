# Service Level Objectives (SLOs)

This document defines the target availability, latency, and reliability metrics for the Modelionn network.

## Availability SLOs

| Service                 | Target             | Notes                                             |
| ----------------------- | ------------------ | ------------------------------------------------- |
| **Registry API**        | 99.5% uptime       | Excludes planned maintenance windows              |
| **IPFS Storage**        | 99.0% uptime       | Content-addressed circuits and proofs             |
| **Redis Cache/Lock**    | 99.0% uptime       | Dispatch locks, rate limiter state, session cache |
| **PostgreSQL Database** | 99.5% uptime       | Proof job state, audit trail, API keys            |
| **Web Dashboard**       | 99.0% uptime       | Next.js frontend CDN delivery                     |
| **Celery Worker Pool**  | 99.0% availability | Async proof dispatch and aggregation              |

## Latency SLOs (p95)

| Operation                   | Target    | Notes                                                         |
| --------------------------- | --------- | ------------------------------------------------------------- |
| **Proof Job Status**        | < 500ms   | GET `/proofs/jobs/{task_id}`                                  |
| **Circuit Upload**          | < 2000ms  | POST `/circuits` with IPFS hash                               |
| **Proof Request**           | < 1500ms  | POST `/proofs` to queue job                                   |
| **Circuit List (10 items)** | < 800ms   | GET `/circuits?page_size=10`                                  |
| **Dashboard Load**          | < 2000ms  | Full page render (First Contentful Paint)                     |
| **Proof Partition**         | < 5000ms  | Async Celery task (circuit → partitions)                      |
| **Proof Dispatch**          | < 10000ms | Assign partitions to miners (incl. network latency)           |
| **Proof Verification**      | < 30000ms | Cross-validator proof check (p95, depends on partition count) |

## Error Rate SLOs

| Service                       | Target       | Notes                                        |
| ----------------------------- | ------------ | -------------------------------------------- |
| **5xx Server Errors**         | < 0.1%       | Exclude rate limit 429 responses             |
| **Proof Generation Failures** | < 5%         | Timeouts, invalid partitions, offline miners |
| **IPFS Upload Failures**      | < 1%         | Transient network issues retried             |
| **Nonce Replay Attacks**      | 100% blocked | Zero tolerance; immediate 401 Unauthorized   |

## Throughput SLOs

| Metric                         | Target     | Notes                                 |
| ------------------------------ | ---------- | ------------------------------------- |
| **Proof Jobs Processed**       | ≥ 1000/day | In steady-state network load          |
| **Circuit Uploads**            | ≥ 50/day   | Community-contributed circuits        |
| **Bittensor Provers Online**   | ≥ 10       | Minimum quorum for consensus          |
| **Proof Partitions per 1 GPU** | ≥ 10/min   | Groth16 BN254 baseline on NVIDIA A100 |

## Monitoring & Alerting

### Critical Alerts (page on-call immediately)

- **Registry API down** (5 min of 502/503 errors)
- **PostgreSQL replication lag > 30s** (data consistency risk)
- **Redis connection pool exhausted** (dispatch locks blocked)
- **Proof generation timeout > 20% of jobs** (network degraded)
- **Bittensor validator unreachable** (consensus broken)

### Warnings (notify team, investigate within 1 hour)

- **p95 latency > 2x SLO target** (performance degradation)
- **5xx error rate > 0.5%** (application errors)
- **Prover uptime < 95%** (reliability risk)
- **IPFS pin count exceeding quota** (storage pressure)
- **Celery task queue depth > 1000** (worker backlog)

### Info (log for trend analysis)

- **Hourly proof counts and latency distribution**
- **Hourly error type breakdown (validation, timeout, signature)**
- **Daily audit log entries (circuit uploads, proof requests, access patterns)**

## Backup & Disaster Recovery

- **Database backup frequency**: Daily at 02:00 UTC (full backup)
- **Backup retention**: 30 days (on-premises S3 or Azure Blob)
- **Restore test interval**: Monthly (restore to staging, verify data integrity)
- **RTO (Recovery Time Objective)**: < 4 hours
- **RPO (Recovery Point Objective)**: < 1 hour (max data loss since last backup)

### Backup Encryption

All backups are encrypted with AES-256-GCM:

```bash
# Backup: encrypts with master key before S3 upload
pg_dump | gpg --encrypt --recipient ops@modelionn.com | aws s3 cp - s3://backups/db.sql.gpg

# Restore: downloads, decrypts, restores
aws s3 cp s3://backups/db.sql.gpg - | gpg --decrypt | psql
```

## See Also

- [Monitoring Setup](monitoring-setup.md) — Infrastructure for metrics collection
- [Alert Runbooks](alert-runbooks.md) — Procedures for responding to alerts
- [Disaster Recovery](disaster-recovery.md) — Backup, restore, and failover procedures
- [Capacity Planning](capacity-planning.md) — Scaling strategies
