# Reliability runbook

Operational guide: failure scenarios, detection, and response. Pairs with the Prometheus
alerts in [observability/alerts.yml](../../observability/alerts.yml).

## Service-level objectives (SLOs)

| SLO | Target | Alert |
|-----|--------|-------|
| Availability (non-5xx) | 99.9% | `HighHttp5xxRate` (>5% 5xx for 5m) |
| Search latency p95 | < 500 ms | `HighRequestLatencyP95` (>1s for 10m) |
| Job processing p95 | < 120 s | `JobProcessingSlow` |
| DLQ depth | 0 | `DeadLetterQueueGrowing` |

## Failure scenarios & response

### 1. High 5xx error rate
- **Detect:** `HighHttp5xxRate`, Grafana error-rate panel, spike in error logs.
- **Likely causes:** bad deploy, DB/Redis outage, dependency failure.
- **Response:** check recent ArgoCD sync; if release-related, `git revert` the gitops bump
  (auto-resync) or `argocd app rollback`. Check `/health/ready` per pod for failing
  dependency. Inspect open circuit breakers (`circuit_breaker_state == 2`).

### 2. Circuit breaker open
- **Detect:** `CircuitBreakerOpen`.
- **Meaning:** a downstream (connector source, embedding provider) is failing; calls are
  short-circuited to protect the system.
- **Response:** identify the breaker by `name` label; verify the dependency; the breaker
  half-opens automatically after the reset timeout and closes on success.

### 3. Dead-letter queue growing
- **Detect:** `DeadLetterQueueGrowing` (`dlq_depth > 0`).
- **Response:** query dead-lettered jobs and their `job_events` for the error; fix root cause
  (bad source config, schema drift); `replay_dlq(job_id, connector_id)` to re-enqueue.

### 4. Queue backlog / slow processing
- **Detect:** `JobProcessingSlow`, rising Redis list length.
- **Response:** confirm KEDA/HPA scaled workers up; if capped, raise `maxReplicas`; check for
  a slow source or embedding contention; consider raising worker concurrency.

### 5. Database pressure
- **Detect:** latency rise, pool exhaustion errors.
- **Response:** verify HNSW/GIN/composite indexes are present (migration `0001`); check slow
  queries; confirm cache hit ratio (`LowCacheHitRatio`); scale read load via caching; tune
  pool size.

### 6. Redis outage
- **Impact:** rate limiting fails open (requests still served); cache misses fall through to
  Postgres; Celery cannot enqueue (uploads still accepted, processing resumes when Redis
  returns).
- **Response:** restore Redis; backlog drains automatically (durable jobs in Postgres).

### 7. Pod loss / node drain
- **Behavior:** Deployment recreates pods; PDB preserves `minAvailable`; readiness keeps
  traffic off not-ready pods. Validated by the Chaos Mesh `pod-kill` experiment.

## Graceful shutdown sequence
1. SIGTERM -> readiness flips to draining (LB stops new traffic).
2. `preStop` sleep + grace period lets in-flight requests finish.
3. DB pool and Redis client disposed; workers finish the current task (warm shutdown).
