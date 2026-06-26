# Architecture

Deep-dive documentation for the Enterprise Data Intelligence Platform.

- [System architecture & data flows](#system-architecture) (this file)
- [Database schema](#database-schema)
- [Sequence diagrams](#sequence-diagrams)
- [Event flow](#event-flow)
- [Architecture Decision Records](decisions.md)
- [Per-phase deep dives](phases.md) - decisions, tradeoffs, scalability, failure scenarios, reliability, cost
- [Interview Q&A](interview-qa.md)
- [Reliability runbook](runbook.md)

## System architecture

```mermaid
flowchart TB
  subgraph client [Clients]
    UI[Web / SDK / curl]
  end

  subgraph edge [Edge]
    ING_NGINX[Ingress NGINX]
  end

  subgraph svc [Application services]
    GW["gateway<br/>auth, RBAC, API keys,<br/>connectors, audit"]
    INGEST["ingestion<br/>upload, validation,<br/>metadata, jobs"]
    RET["retrieval<br/>semantic / keyword /<br/>hybrid search, context"]
  end

  subgraph async [Async processing]
    BEAT[Celery Beat]
    WINGEST[worker: ingest queue]
    WEMBED[worker: embed queue]
  end

  subgraph data [Stateful backends]
    PG[("PostgreSQL 16<br/>+ pgvector")]
    REDIS[("Redis<br/>broker / result / cache")]
    S3[("S3 / MinIO")]
  end

  subgraph obs [Observability]
    OTEL[OTel Collector]
    PROM[Prometheus]
    GRAF[Grafana]
    APM[Elastic APM]
  end

  UI --> ING_NGINX --> GW & INGEST & RET
  GW --> PG
  INGEST --> PG
  INGEST -->|enqueue| REDIS
  GW -->|enqueue sync| REDIS
  RET --> PG
  RET --> REDIS
  REDIS --> WINGEST & WEMBED
  BEAT -->|schedule| REDIS
  WINGEST --> PG
  WINGEST --> S3
  WEMBED --> PG
  GW & INGEST & RET & WINGEST & WEMBED -. OTLP .-> OTEL
  OTEL --> PROM --> GRAF
  OTEL -.-> APM
```

### Service boundaries & why

| Service | Responsibility | Scaling driver |
|--------|----------------|----------------|
| gateway | Identity (JWT/API keys), RBAC, connector config, audit | request rate |
| ingestion | Upload, validation, metadata, job orchestration | upload rate / payload size |
| retrieval | Embedding query + vector/keyword/hybrid search | query rate + model memory |
| workers (ingest) | Connector sync, doc processing | queue depth |
| workers (embed) | Embedding generation | queue depth, CPU |

Splitting retrieval from ingestion lets the memory-hungry embedding model scale
independently from the IO-bound upload path, and isolates user-facing search latency from
heavy background processing.

## Database schema

```mermaid
erDiagram
  TENANTS ||--o{ USERS : has
  TENANTS ||--o{ API_KEYS : has
  TENANTS ||--o{ CONNECTOR_CONFIGS : owns
  TENANTS ||--o{ INGESTION_JOBS : owns
  TENANTS ||--o{ DOCUMENTS : owns
  CONNECTOR_CONFIGS ||--o{ INGESTION_JOBS : triggers
  INGESTION_JOBS ||--o{ JOB_EVENTS : logs
  INGESTION_JOBS ||--o{ DOCUMENTS : produces
  DOCUMENTS ||--o{ DOCUMENT_CHUNKS : split_into

  TENANTS { uuid id PK }
  USERS { uuid id PK  string email  string role }
  API_KEYS { uuid id PK  string prefix  string hashed_key  bool revoked }
  CONNECTOR_CONFIGS { uuid id PK  string connector_type  jsonb config  jsonb cursor }
  INGESTION_JOBS { uuid id PK  string idempotency_key  string status  int attempts }
  JOB_EVENTS { bigint id PK  string status  text message }
  DOCUMENTS { uuid id PK  string content_hash  jsonb doc_metadata }
  DOCUMENT_CHUNKS { uuid id PK  int chunk_index  vector embedding  text content }
  AUDIT_LOGS { bigint id PK  string action  int status_code }
```

Key indexing decisions:
- `document_chunks.embedding` -> **HNSW** index (`vector_cosine_ops`) for fast ANN search.
- `document_chunks.content` -> **GIN** index on `to_tsvector('english', content)` for FTS.
- `ingestion_jobs (tenant_id, status, created_at)` composite + partial index on pending jobs.
- Uniqueness on `(tenant_id, content_hash)` and `(tenant_id, idempotency_key)` enforces
  idempotency at the database layer.

## Sequence diagrams

### Upload -> async processing -> searchable

```mermaid
sequenceDiagram
  participant C as Client
  participant I as ingestion
  participant DB as Postgres
  participant R as Redis
  participant W as worker
  participant E as embeddings

  C->>I: POST /ingest/text (Idempotency-Key)
  I->>DB: get-or-create job (unique idempotency_key)
  alt new job
    I->>R: enqueue process_record
  end
  I-->>C: 202 {job_id, status: pending}
  R->>W: deliver task
  W->>DB: upsert document (dedupe by content_hash)
  W->>E: embed(chunks)
  E-->>W: vectors
  W->>DB: insert chunks + embeddings, mark job succeeded
  C->>I: GET /jobs/{id} -> succeeded
```

### Hybrid search

```mermaid
sequenceDiagram
  participant C as Client
  participant RET as retrieval
  participant Ca as Redis cache
  participant DB as Postgres

  C->>RET: POST /search {mode: hybrid}
  RET->>Ca: GET cache key
  alt hit
    Ca-->>RET: cached hits
  else miss
    RET->>RET: embed(query)
    RET->>DB: vector search (HNSW) + FTS (GIN)
    RET->>RET: normalise + weighted fusion (alpha)
    RET->>Ca: SET (ttl 120s)
  end
  RET-->>C: ranked hits
```

## Event flow

```mermaid
stateDiagram-v2
  [*] --> pending: job created
  pending --> running: worker picks up
  running --> succeeded: processed + embedded
  running --> retrying: transient error
  retrying --> running: backoff elapsed
  retrying --> dead_lettered: max attempts exceeded
  dead_lettered --> pending: manual replay
  succeeded --> [*]
```
