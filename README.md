# Enterprise Data Intelligence Platform

A production-grade, Kubernetes-native platform that ingests data from pluggable connectors,
processes it asynchronously, generates embeddings, and serves AI-powered semantic + hybrid
retrieval. Built to demonstrate backend engineering, distributed systems, platform/SRE, and
cloud-native delivery (Helm + ArgoCD GitOps).

> Companion GitOps repo: **data-platform-gitops** (ArgoCD watches it to deploy this app).

## Architecture at a glance

```mermaid
flowchart LR
  UI["Web UI<br/>React SPA (nginx)"] --> GW
  Client --> GW["gateway<br/>auth, RBAC, API keys, rate limit, connectors"]
  Client --> ING["ingestion<br/>upload, validation, metadata, jobs"]
  Client --> RET["retrieval<br/>semantic + hybrid search, context"]
  UI --> ING
  UI --> RET
  ING -->|enqueue| REDIS[("Redis<br/>broker + cache")]
  GW -->|enqueue| REDIS
  REDIS --> WK["celery workers<br/>connector sync, processing, embeddings, DLQ"]
  WK --> PG[("Postgres + pgvector")]
  RET --> PG
  ING --> PG
  GW --> PG
  WK -. traces/metrics .-> OTEL[OTel Collector]
  GW -. traces/metrics .-> OTEL
  RET -. traces/metrics .-> OTEL
  ING -. traces/metrics .-> OTEL
  OTEL --> PROM[Prometheus] --> GRAF[Grafana]
```

## Tech stack

| Layer | Choice |
|------|--------|
| Frontend | React + Vite + TypeScript + Tailwind (SPA, served by nginx) |
| API | FastAPI (3 services: gateway, ingestion, retrieval) |
| Async | Celery + Redis (broker/result/cache), beat scheduler, DLQ |
| Database | PostgreSQL 16 + `pgvector` (HNSW), async SQLAlchemy 2.0 / asyncpg |
| AI | `sentence-transformers` (pluggable; OpenAI swap via config) |
| Observability | OpenTelemetry, Prometheus, Grafana, Elastic APM, structlog JSON |
| Packaging | Docker, Helm, ArgoCD, kind (local K8s) |
| CI | GitHub Actions **and** Jenkins (lint, type, test, security scan, image build/push) |

## Repository layout

```
libs/platform_core/      # shared library: config, db, telemetry, security, reliability,
                         #   cache, connectors framework, embeddings, search, pipeline
services/gateway/        # auth, RBAC, API keys, connector management
services/ingestion/      # upload + validation + job tracking
services/retrieval/      # semantic / keyword / hybrid search + context API
frontend/                # React + Vite SPA: login, ingest, job tracking, semantic search
workers/                 # Celery app + tasks + beat + DLQ
migrations/              # Alembic migrations (pgvector extension + schema + indexes)
deploy/helm/             # umbrella + per-service Helm charts, per-env values
deploy/kind/             # local kind cluster config
observability/           # otel collector, prometheus, alerts, grafana dashboards
jenkins/                 # local Dockerized Jenkins controller (runs the Jenkinsfile)
docs/architecture/       # ADRs, diagrams, schema, interview Q&A (per phase)
tests/                   # unit, integration, load (k6), chaos
scripts/                 # seed + helpers
Jenkinsfile              # declarative CI pipeline (alternative to GitHub Actions)
```

## Quickstart (local, Docker Compose)

```bash
cp .env.example .env
make up          # builds images, starts Postgres+pgvector, Redis, MinIO, services, workers, observability
make migrate     # apply DB schema (also runs automatically via the migrate service)
make seed        # create a demo tenant + sample documents

# Web UI + APIs
open http://localhost:5173        # Web dashboard (login, ingest, jobs, search)
open http://localhost:8000/docs   # gateway
open http://localhost:8001/docs   # ingestion
open http://localhost:8002/docs   # retrieval
open http://localhost:3000        # Grafana (anonymous admin)
open http://localhost:9090        # Prometheus

# Data stores (host ports; in-network the services use the default ports)
# Postgres : localhost:5432   (DBeaver / psql)
# Redis    : localhost:6380   (RedisInsight; 6380 avoids clashing with a local redis on 6379)
#            db0=cache, db1=Celery broker/queues, db2=Celery results
# MinIO    : localhost:9100 (API) / localhost:9101 (console)
```

The frontend reads its API endpoints from a runtime-injected `config.js`, so the same
image works in Compose (absolute `localhost` URLs + CORS) and Kubernetes (relative URLs
routed by the ingress). For hot-reload development: `cd frontend && npm install && npm run dev`.

### Example flow

```bash
# 1. Bootstrap tenant + admin
curl -s localhost:8000/api/v1/auth/bootstrap -H 'content-type: application/json' \
  -d '{"tenant_name":"Acme","tenant_slug":"acme","admin_email":"a@acme.io","admin_password":"secret123"}'

# 2. Login -> JWT
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"a@acme.io","password":"secret123"}' | jq -r .access_token)

# 3. Ingest text
curl -s localhost:8001/api/v1/ingest/text -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"content":"Kubernetes autoscaling adjusts replicas based on CPU and custom metrics."}'

# 4. Search
curl -s localhost:8002/api/v1/search -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"query":"how does autoscaling work","mode":"hybrid","top_k":3}'
```

## Data connectors

Pluggable source connectors (each supports incremental sync, retry, rate limiting, and a
`validate` connection check). Create/validate/sync them from the **Connectors** page in the
UI or via `POST /api/v1/connectors`:

| Type | Notes |
|------|-------|
| `rest` | JSON REST APIs (configurable records path, headers, rate limit) |
| `csv` / `pdf` | usually uploaded on the Ingest page; also pullable from a URL |
| `postgres` | external Postgres; keyset-incremental on a `cursor_field` |
| `mysql` / `mariadb` | external MySQL/MariaDB via async `aiomysql`; the DSN is auto-normalised so plain `mysql://` / `mariadb://` URLs work. **Omit `table` to sync every table** — the primary key is auto-detected per table for keyset incremental sync (OFFSET pagination as fallback), with a per-table cursor |
| `s3` | objects under a bucket/prefix |

Example — sync an entire MariaDB database:

```bash
curl -s localhost:8000/api/v1/connectors -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"shop","connector_type":"mariadb",
       "config":{"dsn":"mariadb://user:pass@host.docker.internal:3306/shop","batch_size":500}}'
# then POST /api/v1/connectors/{id}/validate  and  /api/v1/connectors/{id}/sync
```

Connector syncs commit progress per batch, so the job flips to `running` immediately and the
Jobs page streams a live `ingested batch N (M records so far)` log instead of sitting on
`pending` until completion.

## Local Kubernetes (kind + Helm + ArgoCD)

```bash
make kind-up && make kind-load
make argocd-install
make helm-install            # or let ArgoCD sync from the gitops repo
```

## CI/CD

Two interchangeable CI pipelines run the same gates; **CD is always ArgoCD** (GitOps):

- **GitHub Actions** — [`.github/workflows/ci.yml`](.github/workflows/ci.yml): lint, type-check,
  test, security scan (bandit/pip-audit/Trivy), build & push image to GHCR.
- **Jenkins** — [`Jenkinsfile`](Jenkinsfile): the same stages plus a frontend build, then it
  bumps the image tag in the GitOps repo so ArgoCD reconciles. Run it locally:

  ```bash
  docker compose -f jenkins/docker-compose.yml up -d --build   # UI at http://localhost:8088
  ```

  See [jenkins/README.md](jenkins/README.md) for credentials + job setup. Jenkins does CI;
  it never `kubectl apply`s — ArgoCD owns deployment.

## Quality gates

```bash
make lint typecheck test security
```

## Documentation

Per-phase deep dives (architecture decisions, tradeoffs, scalability, failure scenarios,
reliability, cost, and interview Q&A) live under [docs/architecture](docs/architecture).

## License

MIT
