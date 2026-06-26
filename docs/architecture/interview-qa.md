# Interview Q&A

Curated questions a platform/backend/SRE interviewer might ask about this system, with
answers grounded in the implementation.

## System design & architecture

**Q: Walk me through what happens when a user uploads a document.**
A: The ingestion service validates type/size, computes a content hash, and creates an
ingestion job keyed by an idempotency key (unique per tenant). If the job is new it enqueues
a Celery task and returns `202` with the job id. A worker picks up the task, upserts the
document (dedupe by `(tenant_id, content_hash)`), chunks the text, generates embeddings, and
writes chunks+vectors, marking the job `succeeded` with an append-only event trail. The
client polls `GET /jobs/{id}`.

**Q: Why split into gateway/ingestion/retrieval services?**
A: Different scaling drivers and resource profiles. Retrieval holds a memory-heavy embedding
model and scales on query rate; ingestion is IO-bound and bursty; gateway is auth/config.
Independent deployment + autoscaling + blast-radius isolation justify the split, while a
shared `platform_core` avoids duplication.

**Q: How do you guarantee idempotency with at-least-once delivery?**
A: Database-enforced uniqueness. Jobs are unique on `(tenant_id, idempotency_key)`; documents
on `(tenant_id, content_hash)`. Redelivered/duplicate work converges to the same rows, so
retries are safe without distributed locks. `acks_late` ensures a crashed worker's task is
redelivered.

## Async & reliability

**Q: How does your dead-letter queue work?**
A: Tasks retry with exponential backoff up to `max_retries`. On terminal failure the payload
is routed to the `dlq` queue, the job is marked `dead_lettered`, and a job event records the
reason. Beat publishes DLQ depth as a Prometheus gauge with an alert. `replay_dlq` re-enqueues
after the root cause is fixed.

**Q: Circuit breaker vs retry - when does each fire?**
A: Retries absorb transient, independent faults (a single 503/timeout). The circuit breaker
tracks the *aggregate* failure rate to a dependency; once it crosses the threshold it opens
and fails fast for a cooldown, preventing retry storms from hammering a downed dependency
and causing cascading failures. They compose: retry within a call, breaker across calls.

**Q: How do you autoscale workers on backlog rather than CPU?**
A: KEDA `ScaledObject` with a Redis trigger on queue length; it scales the worker Deployment
(including scale-to-zero for embed) based on `listLength`. CPU-based HPA is the fallback when
KEDA isn't installed.

## Data & AI

**Q: Why pgvector and how is search fast?**
A: One datastore for documents, metadata, and vectors gives transactional consistency and
SQL metadata filtering. An HNSW index (`vector_cosine_ops`) makes ANN search sub-linear.
Embeddings are normalized so cosine distance is meaningful.

**Q: Explain hybrid search.**
A: We run vector search (semantic) and Postgres full-text search (keyword) in parallel,
min-max normalize each score set, then fuse with a tunable `alpha`. This recovers exact-term
matches that pure embeddings miss while keeping semantic recall.

**Q: How would you scale beyond pgvector's limits?**
A: The search and embedding layers are abstracted. Options: partition chunks by tenant, tune
HNSW (`ef_search`), move to IVFFlat for very large sets, or route to a dedicated vector DB
behind the same interface - without touching call sites.

## Performance

**Q: Your caching strategy and invalidation?**
A: Cache-aside in Redis with short TTLs for read-heavy search. Keys are namespaced and
versioned so we can invalidate a whole class (e.g. a tenant's search results after new
ingestion) via `invalidate_namespace`, which `SCAN`s rather than blocking Redis with `KEYS`.

**Q: How do you keep the async API from blocking?**
A: Async SQLAlchemy + asyncpg end-to-end; no sync IO on the event loop. CPU/model-bound work
is pushed to Celery. Connection pools are tuned per service with `pre_ping` and `recycle` to
survive DB failover.

## Security

**Q: How are API keys stored and verified?**
A: We generate `prefix.secret`, show it once, and store only an HMAC-SHA256 hash (salted).
Lookups are by indexed prefix, then a constant-time compare of the hash - so a DB leak does
not expose usable keys.

**Q: How is multi-tenant isolation enforced?**
A: `tenant_id` on every owned row, carried in JWT/API-key claims, and applied as a predicate
in every query. Uniqueness constraints are tenant-scoped. (For stricter isolation we can move
to RLS or schema-per-tenant.)

## Kubernetes & deployment

**Q: Difference between liveness, readiness, and startup probes here?**
A: Liveness = process healthy (restart if not). Readiness = dependencies reachable and not
draining (remove from Service endpoints if not), which also powers graceful shutdown. Startup
= gates the other probes while slow init (model load) completes.

**Q: How do rolling vs blue/green deploys differ in this repo?**
A: Stateless services use RollingUpdate (`maxUnavailable: 0`). The data-plane `retrieval`
service uses an Argo Rollout blue/green: a green ReplicaSet runs alongside blue, a Prometheus
`AnalysisTemplate` checks success rate, and promotion is manual/gated - giving instant
rollback by keeping blue warm.

**Q: How does GitOps promotion/rollback work?**
A: CI builds and pushes an image tag. Promotion is a PR bumping `imageTag` in the target
env's `environments/<env>/values.yaml` in the gitops repo; ArgoCD auto-syncs (prod is
manual). Rollback is `git revert` (ArgoCD reconciles) or `argocd app rollback`.

**Q: What protects availability during node maintenance?**
A: PodDisruptionBudgets (`minAvailable`) block voluntary evictions from taking the last
replica, combined with multiple replicas and anti-affinity-friendly scheduling.
