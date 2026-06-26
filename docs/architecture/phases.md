# Per-phase deep dives

For each phase: architecture decisions, tradeoffs, scalability strategy, failure scenarios,
reliability considerations, and cost implications. Interview Q&A is collected in
[interview-qa.md](interview-qa.md).

---

## Phase 0 - Scaffold & foundation

**Decisions:** Shared `platform_core` library so config, DB, telemetry, security, and
reliability are implemented once and reused by every service/worker. Single image,
command-selected role. 12-factor config via `pydantic-settings`.

**Tradeoffs:** A shared lib couples services to a common version (mitigated by a stable,
well-tested core). A monorepo simplifies refactors at the cost of finer-grained ownership.

**Scalability:** Stateless services behind a Service/Ingress scale horizontally; all state
lives in Postgres/Redis/S3.

**Failure scenarios:** DB or Redis unreachable at boot -> readiness fails, pod kept out of
rotation until healthy. Telemetry endpoint down -> instrumentation degrades silently, never
crashes the app.

**Reliability:** Liveness/readiness/startup probes; graceful shutdown drains traffic and
disposes the pool.

**Cost:** Minimal - shared image reduces registry/storage; local stack is free.

---

## Phase 1 - Data connectors

**Decisions:** A `BaseConnector` contract (`validate` + async `fetch` yielding cursor-bearing
batches) with a registry keyed by `ConnectorType`. Cross-cutting concerns - incremental
sync (persisted `cursor`), retries (`tenacity`), rate limiting (token bucket), circuit
breaking (`pybreaker`) - are shared, not reimplemented per connector.

**Tradeoffs:** A uniform `Record` shape simplifies the pipeline but flattens
source-specific richness (kept in `metadata`). Keyset/cursor pagination (vs OFFSET) is
faster but requires a monotonic cursor column.

**Scalability:** Each connector run is a Celery task; many connectors sync in parallel
across workers. Batching bounds memory; cursors enable resumable, incremental syncs.

**Failure scenarios:** Source 429/5xx -> retried with backoff, then circuit-opens to fail
fast. Partial sync crash -> cursor persisted per batch, so re-run resumes without
re-ingesting. Malformed records -> validated and skipped, surfaced in job events.

**Reliability:** `validate()` gives a pre-flight check before scheduling syncs; rate limiter
protects both us and the upstream.

**Cost:** Rate limiting avoids overage charges on metered APIs; incremental sync avoids
reprocessing (compute + embedding cost).

---

## Phase 2 - Ingestion pipeline

**Decisions:** Thin, fast upload API that validates (type/size/empty), extracts metadata,
creates an idempotent job, enqueues, and returns `202`. Heavy work is fully async. Job +
append-only `job_events` give complete processing history.

**Tradeoffs:** Async-first means clients poll job status (eventual consistency) rather than
getting synchronous results - the right call for large/slow ingestion.

**Scalability:** Upload path is IO-bound and scales on request rate; processing scales on
queue depth independently.

**Failure scenarios:** Duplicate upload -> idempotency key returns the original job. Worker
dies mid-job -> `acks_late` redelivers; idempotent upsert prevents duplicates. Oversized/
unsupported file -> rejected at the edge (413/415).

**Reliability:** DB-enforced idempotency; every state transition recorded for auditability
and debugging.

**Cost:** Bounded upload size and dedupe avoid wasted storage/compute.

---

## Phase 3 - Async processing

**Decisions:** Queues segregated by workload (`ingest` vs `embed`) so model-bound work
doesn't starve IO work. `acks_late` + `reject_on_worker_lost` + `prefetch=1` for fair,
at-least-once delivery. Exponential backoff retries; terminal failures -> DLQ + job marked
`dead_lettered`; `replay_dlq` re-enqueues after a fix. Beat schedules incremental syncs and
publishes DLQ depth.

**Tradeoffs:** At-least-once (not exactly-once) - we lean on idempotency instead of
expensive distributed transactions. `prefetch=1` maximizes fairness at a small throughput
cost.

**Scalability:** HPA on CPU for steady load; KEDA scales workers on Redis queue length
(including scale-to-zero for the embed queue) in staging/prod.

**Failure scenarios:** Poison message -> retried then dead-lettered, never blocks the queue.
Thundering herd after outage -> backoff + jitter + bounded concurrency. Beat single point ->
runs as a `Recreate` singleton; missed ticks self-heal on next interval.

**Reliability:** Visibility timeout returns un-acked tasks; DLQ depth is alerted on.

**Cost:** Scale-to-zero and queue-based autoscaling mean you pay for workers only when there
is work.

---

## Phase 4 - AI context layer

**Decisions:** Sentence-aware chunking with overlap; normalized embeddings + cosine HNSW;
three modes - semantic (pgvector), keyword (Postgres FTS), hybrid (min-max normalized,
alpha-weighted fusion). Metadata filtering via JSONB predicates. Model warmed at startup.

**Tradeoffs:** HNSW trades a little recall for big latency wins (tunable `m`/`ef`). Hybrid
fusion adds a query but markedly improves relevance on keyword-heavy queries. Larger
chunks = fewer rows but coarser retrieval.

**Scalability:** Retrieval replicas scale on query rate; HNSW keeps search sub-linear.
Embedding generation is offloaded to the `embed` workers.

**Failure scenarios:** Model load failure -> provider raises, readiness reflects it. Empty
index -> returns no hits (not an error). Cache staleness -> short TTL + namespace
invalidation on ingest.

**Reliability:** Search is read-only and cache-fronted; degrades gracefully if cache is down
(fall through to DB).

**Cost:** Local embeddings = $0 inference. Caching cuts repeated compute. Memory is the main
cost lever for retrieval pods (sized larger in values).

---

## Phase 5 - Observability

**Decisions:** Three pillars - structured JSON logs (structlog, trace-correlated), metrics
(Prometheus via instrumentator + custom domain metrics), traces (OpenTelemetry OTLP, auto-
instrumented FastAPI/SQLAlchemy/Redis/Celery). Grafana dashboards + Prometheus alert rules
encode SLOs. Elastic APM optional for APM-style traces.

**Tradeoffs:** Full tracing is costly at scale -> tail/probabilistic sampling (10% in prod).
More cardinality = more storage; labels kept disciplined.

**Scalability:** Collector batches and back-pressures; sampling bounds trace volume.

**Failure scenarios:** Collector down -> spans dropped, app unaffected (fire-and-forget).
Metric endpoint scrape failure -> alert on `up == 0`.

**Reliability:** RED metrics (rate/errors/duration) + USE for resources; alerts on 5xx rate,
p95 latency, DLQ growth, open circuit breakers, low cache hit ratio.

**Cost:** Sampling + retention policies + label hygiene are the main cost controls.

---

## Phase 6 - Reliability, performance, security

**Decisions:**
- *Reliability:* circuit breakers + retries/backoff around every external dependency;
  graceful shutdown; liveness/readiness/startup probes.
- *Performance:* Redis cache-aside with TTL + namespace invalidation; HNSW/GIN/composite
  indexes; async pooling with `pre_ping` + recycle; keyset pagination; query shaping.
- *Security:* Argon2 passwords; short-lived JWT; hashed API keys (shown once); RBAC
  hierarchy; per-identity rate limiting (fail-open); audit logging; K8s Secrets / External
  Secrets; non-root containers, dropped capabilities, NetworkPolicies.

**Tradeoffs:** Caching adds staleness (bounded by TTL/invalidation). Fail-open rate limiting
favors availability over strict enforcement during Redis outages. Logical multi-tenancy
trades isolation for cost/simplicity.

**Scalability:** Caching and pooling shed load off Postgres; indexes keep queries flat as
data grows.

**Failure scenarios:** Downstream brownout -> breaker opens, users get fast failures + alert
fires. Cache stampede -> short TTLs + per-key population. Token theft -> short expiry + key
revocation + audit trail.

**Reliability:** Defense in depth; every dependency call is guarded.

**Cost:** Cache + indexes reduce DB size/IOPS (cost). Argon2 is CPU-heavy by design - sized
into requests.

---

## Phase 7 - Cloud-native deployment

**Decisions:** Helm umbrella chart templating Deployments/Services/HPA/PDB per service via a
values map; ConfigMap (non-secret) + Secret (sensitive) split; Ingress fan-out by path;
default-deny NetworkPolicies; rolling updates by default, Argo Rollouts blue/green for the
data plane (`retrieval`) with Prometheus analysis gating promotion. Migrations run as a Helm
pre-upgrade hook Job. ArgoCD ApplicationSet renders one app per environment (multi-source:
chart from app repo, image tags from gitops repo); prod sync is manual.

**Tradeoffs:** Blue/green doubles pods briefly (cost) but enables instant rollback and
zero-downtime cutover; rolling is cheaper for stateless services. Multi-source ArgoCD is
powerful but more moving parts than a single source.

**Scalability:** HPA (CPU/mem) for services, KEDA (queue depth) for workers; PDBs keep
minimum availability during voluntary disruptions.

**Failure scenarios:** Bad release -> blue/green analysis fails, promotion blocked, traffic
stays on blue; or `git revert` + ArgoCD self-heal. Node drain -> PDB prevents taking the
last replica. Failed migration -> hook Job fails, upgrade aborts before pods roll.

**Reliability:** GitOps = declarative, auditable, self-healing desired state; rollbacks are
git operations.

**Cost:** HPA/KEDA scale to demand; blue/green surge and over-provisioned minReplicas are the
main cost knobs (tuned down in dev/local).

---

## Phase 8 - Production readiness

**Decisions:** k6 ramp + spike load tests with SLO thresholds (p95 < 500ms, error < 1%);
Chaos Mesh experiments (pod-kill, Postgres latency injection) to validate self-healing,
PDBs, timeouts, retries, and breakers; performance tuning loop driven by Grafana.

**Tradeoffs:** Chaos in staging (not prod initially) to build confidence safely; synthetic
load may not capture real traffic shapes (complement with shadow traffic later).

**Scalability:** Load tests identify the per-replica ceiling and validate autoscaling
behavior under spikes.

**Failure scenarios exercised:** pod loss, dependency latency, queue backlog, cache outage.
Each maps to an alert and an expected automated recovery.

**Reliability:** Closes the loop - the SLOs in alerts are the SLOs verified under load/chaos.

**Cost:** Load/chaos runs are short-lived and cheap relative to a production incident; tuning
right-sizes requests/limits to cut steady-state cost.
