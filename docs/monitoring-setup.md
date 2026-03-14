# Monitoring Setup Guide — Modelionn

This guide covers setting up and using the built-in Prometheus, Grafana, and Alertmanager monitoring stack.

---

## 1. Architecture

```
Registry API ──/metrics──→ Prometheus ──→ Grafana (dashboards)
                                │
                                └──→ Alertmanager ──→ Webhook / Slack / Email
```

All monitoring services are included in `docker-compose.yml` (dev) and `docker-compose.prod.yml` (production).

---

## 2. Quick Start

```bash
# Development
docker compose up -d

# Production
docker compose -f docker-compose.prod.yml up -d
```

Services will be available at:

| Service | Dev URL | Prod URL |
|---------|---------|----------|
| **Prometheus** | http://localhost:9090 | Behind reverse proxy (no direct port) |
| **Grafana** | http://localhost:3001 | Behind reverse proxy (no direct port) |
| **Alertmanager** | http://localhost:9093 | Behind reverse proxy (no direct port) |

---

## 3. Prometheus

### 3.1 Configuration

Located at `docker/prometheus/prometheus.yml`:

- **Scrape interval**: 10 seconds
- **Target**: `registry:8000/metrics`
- **Alerting**: Routes to `alertmanager:9093`
- **Rule files**: `alerts.yml`

### 3.2 Available Metrics

The Registry API exposes the following Prometheus metrics at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `modelionn_http_requests_total` | Counter | Total HTTP requests by method, path, status |
| `modelionn_http_request_duration_seconds` | Histogram | Request latency distribution |
| `modelionn_http_requests_in_flight` | Gauge | Currently active requests |
| `modelionn_proofs_generated_total` | Counter | Total proofs generated |
| `modelionn_proof_queue_depth` | Gauge | Jobs waiting in proof queue |
| `modelionn_provers_online` | Gauge | Number of online provers |
| `modelionn_proof_timeout_total` | Counter | Proof generation timeouts |
| `modelionn_proof_dispatch_failures_total` | Counter | Failed proof dispatch attempts |
| `modelionn_api_key_rejections_total` | Counter | Rejected API key attempts |
| `modelionn_nonce_replays_total` | Counter | Detected nonce replay attacks |
| `modelionn_ipfs_up` | Gauge | IPFS connectivity status |
| `modelionn_celery_workers_online` | Gauge | Active Celery workers |

### 3.3 Useful PromQL Queries

```promql
# Request rate (last 5 minutes)
rate(modelionn_http_requests_total[5m])

# P99 latency
histogram_quantile(0.99, rate(modelionn_http_request_duration_seconds_bucket[5m]))

# Error rate (5xx responses)
rate(modelionn_http_requests_total{status=~"5.."}[5m]) / rate(modelionn_http_requests_total[5m])

# Proof completion rate
rate(modelionn_proofs_generated_total[1h])
```

---

## 4. Grafana

### 4.1 Initial Login

- **URL**: http://localhost:3001
- **Default credentials**: `admin` / `admin` (change immediately in production)
- Set `GRAFANA_ADMIN_PASSWORD` in `.env` for production

### 4.2 Pre-Configured Dashboard

A dashboard is automatically provisioned from `grafana/dashboard.json` with:

| Panel | Type | Description |
|-------|------|-------------|
| HTTP Requests/sec | Time series | Incoming request rate |
| Request Latency (avg) | Time series | Average response time |
| In-Flight Requests | Gauge | Active request count |
| Proofs Generated | Stat | Total proofs created |

### 4.3 Adding Custom Panels

1. Open Grafana → Dashboards → Modelionn
2. Click **Add panel**
3. Select **Prometheus** datasource (auto-configured)
4. Enter a PromQL query (see section 3.3)
5. Save the dashboard

### 4.4 Exporting Dashboard Changes

To persist dashboard changes across deployments:

```bash
# Export the current dashboard from Grafana API
curl -s http://admin:admin@localhost:3001/api/dashboards/uid/modelionn \
  | jq '.dashboard' > grafana/dashboard.json
```

---

## 5. Alertmanager

### 5.1 Configuration

Located at `docker/alertmanager/alertmanager.yml`. By default, alerts are routed to a webhook receiver.

### 5.2 Alert Rules

13 rules defined in `docker/prometheus/alerts.yml`:

| Alert | Severity | Trigger |
|-------|----------|---------|
| ProofTimeoutSpikeRate | Critical | > 10% timeout rate in 15m |
| HighProofDispatchFailureRate | Critical | > 20% dispatch failures |
| NoOnlineProvers | Critical | 0 provers online |
| LowProverCount | Warning | < 3 provers online |
| MetricsEndpointDown | Critical | Registry metrics unreachable |
| HighAPIKeyRejectionRate | Warning | > 10 rejections/sec |
| NonceReplayAttack | Critical | > 50 replays in 5m |
| IPFSUnreachable | Critical | IPFS node down |
| HighPartitionOrphanRate | Warning | > 20 reassignments in 30m |
| HighProofQueueDepth | Warning | > 100 queued jobs |
| ProofP99LatencyHigh | Warning | P99 > 300s |
| CeleryWorkerDown | Critical | No active workers |

### 5.3 Configuring Slack Notifications

Edit `docker/alertmanager/alertmanager.yml`:

```yaml
global:
  slack_api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'

receivers:
  - name: 'slack-critical'
    slack_configs:
      - channel: '#modelionn-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
        send_resolved: true

  - name: 'slack-warnings'
    slack_configs:
      - channel: '#modelionn-warnings'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

route:
  receiver: 'slack-warnings'
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'slack-critical'
      repeat_interval: 1h
```

### 5.4 Configuring PagerDuty

```yaml
receivers:
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<YOUR_PAGERDUTY_SERVICE_KEY>'
        severity: 'critical'
```

### 5.5 Testing Alerts

```bash
# Silence an alert for maintenance
curl -X POST http://localhost:9093/api/v2/silences -d '{
  "matchers": [{"name": "alertname", "value": "LowProverCount"}],
  "startsAt": "2024-01-01T00:00:00Z",
  "endsAt": "2024-01-01T02:00:00Z",
  "comment": "Scheduled maintenance",
  "createdBy": "admin"
}'

# View active alerts
curl http://localhost:9093/api/v2/alerts
```

---

## 6. Production Checklist

- [ ] Set `GRAFANA_ADMIN_PASSWORD` in `.env`
- [ ] Configure Alertmanager receivers (Slack, PagerDuty, or email)
- [ ] Place Grafana and Prometheus behind reverse proxy with authentication (see `docs/tls-setup.md`)
- [ ] Adjust Prometheus retention if disk is limited: add `--storage.tsdb.retention.time=7d` to command
- [ ] Add additional scrape targets if scaling to multiple registry instances
- [ ] Set up Grafana alerting for dashboard-specific thresholds
- [ ] Test alert routing: `curl -X POST http://localhost:9093/api/v2/alerts -d '[...]'`
