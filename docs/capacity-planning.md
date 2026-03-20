# Capacity Planning Guide — ZKML

This guide helps operators size their deployment for expected workloads.

---

## 1. Service Resource Profiles

### Production Defaults (docker-compose.prod.yml)

| Service              | CPU Limit | RAM Limit | Storage     | Notes                              |
| -------------------- | --------- | --------- | ----------- | ---------------------------------- |
| **Registry API**     | 2 cores   | 1 GB      | —           | Stateless; scale horizontally      |
| **Worker (Celery)**  | 4 cores   | 2 GB      | —           | CPU-bound proof dispatch           |
| **Beat (Scheduler)** | 0.5 cores | 256 MB    | —           | Single instance only               |
| **PostgreSQL**       | —         | —         | 10–50 GB    | Grows with proofs and circuits     |
| **Redis**            | —         | —         | 512 MB–2 GB | Mostly ephemeral (cache + broker)  |
| **IPFS**             | —         | —         | 50–500 GB   | Grows with circuit/proof artifacts |
| **Web (Next.js)**    | —         | —         | —           | Lightweight; 256 MB RAM typical    |
| **Prometheus**       | —         | —         | 5–20 GB     | 15-day default retention           |
| **Grafana**          | —         | —         | 100 MB      | Dashboards and config only         |

---

## 2. Scaling by Workload Tier

### Small (< 100 proof jobs/day)

| Resource | Recommendation                |
| -------- | ----------------------------- |
| Host     | 4 CPU, 8 GB RAM, 100 GB SSD   |
| Workers  | 1 Celery worker (default)     |
| Registry | 1 instance                    |
| Database | PostgreSQL with WAL archiving |

### Medium (100–1,000 proof jobs/day)

| Resource | Recommendation                                |
| -------- | --------------------------------------------- |
| Host     | 8 CPU, 16 GB RAM, 500 GB SSD                  |
| Workers  | 2–4 Celery workers                            |
| Registry | 2 instances behind load balancer              |
| Database | PostgreSQL with daily backups + WAL streaming |
| Redis    | Dedicated Redis instance with persistence     |

```bash
# Scale workers
docker compose -f docker-compose.prod.yml up -d --scale worker=4
```

### Large (1,000+ proof jobs/day)

| Resource   | Recommendation                                      |
| ---------- | --------------------------------------------------- |
| Host(s)    | 16+ CPU, 32+ GB RAM per node                        |
| Workers    | 8+ Celery workers across nodes                      |
| Registry   | 4+ instances with sticky sessions                   |
| Database   | Managed PostgreSQL (RDS/CloudSQL) with replicas     |
| Redis      | Managed Redis (ElastiCache/Memorystore)             |
| IPFS       | Cluster mode with multiple nodes                    |
| Monitoring | Dedicated Prometheus + Thanos for long-term storage |

---

## 3. Database Sizing

| Data Type  | Row Size (approx) | Growth Rate                        |
| ---------- | ----------------- | ---------------------------------- |
| Proof jobs | ~500 bytes/row    | 1 row per job                      |
| Proofs     | ~300 bytes/row    | 1 row per completed job            |
| Circuits   | ~400 bytes/row    | Grows slowly (new circuit uploads) |
| Audit logs | ~200 bytes/row    | 1–5 rows per API call              |
| API keys   | ~200 bytes/row    | Grows slowly                       |

**Example**: 1,000 proofs/day × 365 days × 1 KB (job + proof) ≈ **365 MB/year** in PostgreSQL. Audit logs may dominate at high traffic.

**Recommendation**: Start with 10 GB storage, monitor with `pg_database_size()`, plan for 2× headroom.

---

## 4. IPFS Storage

Circuit artifacts (R1CS, WASM, keys) are typically 1–100 MB each. Proofs are smaller (1–10 KB).

| Circuits | Avg Size | Total Storage |
| -------- | -------- | ------------- |
| 100      | 10 MB    | 1 GB          |
| 1,000    | 10 MB    | 10 GB         |
| 10,000   | 10 MB    | 100 GB        |

**Tip**: IPFS deduplicates content automatically. Multiple proofs using the same circuit share the circuit artifact storage.

---

## 5. Network Bandwidth

| Traffic Type           | Bandwidth                              |
| ---------------------- | -------------------------------------- |
| API requests/responses | Low (< 1 Mbps typical)                 |
| Circuit upload         | Bursty (10–100 MB per upload)          |
| Proof download         | Low (1–10 KB per proof)                |
| IPFS swarm             | Moderate (depends on pinning activity) |
| Bittensor P2P          | Low (synapse messages are < 10 KB)     |

For most deployments, **100 Mbps** is sufficient. High-throughput deployments with many concurrent circuit uploads may need **1 Gbps**.

---

## 6. Monitoring Thresholds

Configure alerts in `docker/prometheus/alerts.yml` based on your capacity:

| Metric                                        | Warning   | Critical  | Action                                      |
| --------------------------------------------- | --------- | --------- | ------------------------------------------- |
| `zkml_proof_queue_depth`                 | > 50      | > 100     | Scale workers                               |
| `zkml_http_request_duration_seconds` P99 | > 5s      | > 30s     | Scale registry or investigate slow queries  |
| `zkml_http_requests_in_flight`           | > 50      | > 100     | Scale registry                              |
| PostgreSQL connections                        | > 80% max | > 95% max | Increase `max_connections` or add pgbouncer |
| Disk usage                                    | > 70%     | > 85%     | Expand volume or prune old data             |

---

## 7. Scaling Checklist

When scaling up:

- [ ] Increase worker count: `--scale worker=N`
- [ ] Increase registry instances: `--scale registry=N` (add load balancer)
- [ ] Increase PostgreSQL `max_connections` (default: 100, recommend 200+ for medium tier)
- [ ] Monitor Redis memory usage — switch to dedicated instance if > 2 GB
- [ ] Enable PostgreSQL connection pooling (pgbouncer) at > 4 registry instances
- [ ] Review IPFS garbage collection settings for storage-constrained environments
- [ ] Set up log rotation for Docker container logs (`--log-opt max-size=50m --log-opt max-file=5`)
