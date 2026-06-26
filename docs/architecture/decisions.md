# Architecture Decision Records (ADRs)

Concise records of the significant, hard-to-reverse decisions and their rationale.

## ADR-0001: pgvector over a dedicated vector database

**Status:** Accepted

**Context:** We need vector storage + ANN search for semantic retrieval. Options: pgvector
in Postgres, or a dedicated store (Qdrant/Weaviate/Milvus).

**Decision:** Use `pgvector` inside the primary Postgres.

**Consequences:**
- (+) One datastore to operate, back up, and secure; transactional consistency between
  documents, chunks, and embeddings; metadata filtering via SQL/JSONB for free.
- (+) HNSW indexing gives sub-linear ANN search adequate for millions of chunks.
- (-) At very large scale (100M+ vectors) a dedicated store may outperform. Mitigated by
  the `EmbeddingProvider`/search abstraction, which lets us shard or swap later.

## ADR-0002: Pluggable embedding provider, local-first

**Status:** Accepted

**Context:** Embeddings can come from local models or hosted APIs (cost + latency + privacy
tradeoffs).

**Decision:** Define an `EmbeddingProvider` interface with a local sentence-transformers
default and an OpenAI implementation selectable via `EMBEDDING_PROVIDER`.

**Consequences:** Zero API cost and full reproducibility locally; data never leaves the
cluster; a one-line config swap moves to higher-quality hosted embeddings when justified.

## ADR-0003: Celery + Redis for async processing

**Status:** Accepted

**Context:** Ingestion is bursty and long-running; the API must stay responsive.

**Decision:** Offload to Celery workers with Redis as broker/result backend. Dedicated
queues (`ingest`, `embed`, `dlq`, `periodic`), `acks_late`, and idempotent processing.

**Consequences:** Independent scaling of API vs workers; at-least-once delivery made safe by
idempotency; DLQ isolates poison messages. Redis as broker is simpler than RabbitMQ/Kafka
but offers weaker delivery guarantees - acceptable given DB-enforced idempotency.

## ADR-0004: Async SQLAlchemy 2.0 + asyncpg

**Status:** Accepted

**Decision:** Use the async ORM end-to-end so FastAPI request handlers never block the event
loop on IO, with a tuned connection pool per service.

**Consequences:** High concurrency per replica; care needed to avoid sync calls in async
paths. Alembic migrations run synchronously (psycopg) which is fine for one-shot jobs.

## ADR-0005: Two repos - app monorepo + GitOps repo

**Status:** Accepted

**Decision:** Application code, Helm charts, and CI live in `data-platform`; ArgoCD watches a
separate `data-platform-gitops` repo holding Application manifests and per-env overrides.

**Consequences:** Clean separation of "what the software is" from "what is deployed where";
promotion and rollback are auditable git operations; avoids CI writing back to the app repo.

## ADR-0006: Idempotency enforced at the database

**Status:** Accepted

**Decision:** Unique constraints on `(tenant_id, idempotency_key)` for jobs and
`(tenant_id, content_hash)` for documents.

**Consequences:** Retries and duplicate submissions converge to a single row regardless of
race conditions, without distributed locks. The DB is the source of truth for dedupe.

## ADR-0007: Multi-tenancy via shared schema + tenant_id

**Status:** Accepted

**Decision:** Single shared schema with a `tenant_id` column on every tenant-owned table and
tenant scoping enforced in every query (and embedded in JWT/API-key claims).

**Consequences:** Operationally simple and cost-efficient; isolation is logical not physical.
For regulated workloads, the model can evolve to schema-per-tenant or row-level security.

## ADR-0008: One container image, command-selected role

**Status:** Accepted

**Decision:** Build a single image; the runtime command selects gateway/ingestion/retrieval/
worker/beat.

**Consequences:** Simpler CI and registry, guaranteed dependency parity across processes,
faster image cache reuse. Slightly larger image than per-service minimal builds.
