# Rate Limiting Tuning Guide

The ZKML registry uses a sliding-window rate limiter with Redis (primary) and in-memory (fallback) backends.

## Architecture

```
Request → RateLimitMiddleware
           ├─ Redis available? → sliding window in Redis (ZADD/ZRANGEBYSCORE)
           └─ No Redis?        → in-memory defaultdict with periodic cleanup
```

## Configuration

All settings are via environment variables prefixed with `ZKML_`:

| Variable                          | Default | Description                                                                    |
| --------------------------------- | ------- | ------------------------------------------------------------------------------ |
| `ZKML_RATE_LIMIT_PER_MINUTE` | `60`    | Max requests per client per minute                                             |
| `ZKML_RATE_LIMIT_BURST`      | `10`    | Extra burst allowance above the per-minute rate                                |
| `ZKML_TRUSTED_PROXIES`       | `""`    | Comma-separated CIDR blocks for proxy trust (e.g., `10.0.0.0/8,172.16.0.0/12`) |

## Exempt Paths

The following paths bypass rate limiting entirely:

- `/health`, `/health/ready` — liveness/readiness probes
- `/docs`, `/redoc`, `/openapi.json` — API documentation
- `/metrics` — Prometheus scrape endpoint

## Concurrent Connection Limit

A per-client concurrent connection cap (`_MAX_CONCURRENT_PER_CLIENT = 50`) prevents slow-loris attacks. This is separate from the rate limit.

## Trusted Proxy Configuration

When running behind a reverse proxy (nginx, Cloudflare, AWS ALB):

```bash
# Trust AWS ALB and internal Docker network
ZKML_TRUSTED_PROXIES="10.0.0.0/8,172.16.0.0/12"
```

**IP extraction logic:** The middleware walks `X-Forwarded-For` entries right-to-left, skipping any IP in the trusted CIDR list, and uses the first non-trusted IP as the client identity.

**Without trusted proxies:** `X-Forwarded-For` is ignored entirely, and the direct `client.host` is used. This prevents IP spoofing.

## Tuning for Production

### High-Traffic APIs (>1000 req/s)

```bash
ZKML_RATE_LIMIT_PER_MINUTE=300
ZKML_RATE_LIMIT_BURST=50
```

### Proof Submission Endpoints

The `/proofs/request` and `/proofs/request/batch` endpoints are the most expensive. Consider applying a lower per-route limit via an additional middleware or API gateway.

### Redis Scaling

- Use Redis Cluster for horizontal scaling.
- Monitor `redis_memory_used_bytes` in Prometheus.
- Set `maxmemory-policy allkeys-lru` to prevent OOM.

## Monitoring

Key metrics to watch:

- **`http_requests_total{status="429"}`** — rate limit rejections
- **Rate limiter memory** — In-memory dict size (only relevant when Redis is down)

## Testing Rate Limits

```bash
# Quick local test with curl
for i in $(seq 1 70); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/circuits)
  echo "Request $i: $code"
done
# Requests 61-70 should return 429
```

## Troubleshooting

| Symptom                  | Cause                                    | Fix                                               |
| ------------------------ | ---------------------------------------- | ------------------------------------------------- |
| All requests get 429     | Redis down + accumulated in-memory state | Restart API server or fix Redis                   |
| Legitimate users blocked | Rate too low for traffic pattern         | Increase `RATE_LIMIT_PER_MINUTE`                  |
| 429 only in tests        | Cross-test state leakage                 | Ensure `_reset_rate_limiter` autouse fixture runs |
