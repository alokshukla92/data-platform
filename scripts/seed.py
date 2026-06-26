"""Seed a demo tenant, admin user, and a handful of documents for local exploration.

Run with the local stack up:  ``python scripts/seed.py``  (or ``make seed``).
"""

from __future__ import annotations

import asyncio

from platform_core.connectors.base import Record
from platform_core.db import session_scope
from platform_core.logging import configure_logging, get_logger
from platform_core.models import Role, Tenant, User
from platform_core.pipeline import upsert_document
from platform_core.security import hash_password
from sqlalchemy import select

configure_logging(service_name="seed", json_logs=False)
log = get_logger(__name__)

SAMPLE_DOCS = [
    (
        "Kubernetes HPA",
        "Horizontal Pod Autoscaling scales the number of pod replicas based on "
        "observed CPU utilization or custom metrics exposed via the metrics API.",
    ),
    (
        "Circuit breaker",
        "A circuit breaker prevents cascading failures by failing fast once a "
        "downstream dependency crosses an error threshold, then probing for recovery.",
    ),
    (
        "Vector search",
        "pgvector stores embeddings in Postgres and supports approximate nearest "
        "neighbour search using HNSW indexes with cosine distance for semantic retrieval.",
    ),
    (
        "GitOps",
        "ArgoCD continuously reconciles the cluster state against manifests stored in a "
        "git repository, enabling declarative deployments, rollbacks, and environment promotion.",
    ),
]


async def main() -> None:
    async with session_scope() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name="Demo Corp", slug="demo")
            db.add(tenant)
            await db.flush()
            db.add(
                User(
                    tenant_id=tenant.id,
                    email="admin@demo.io",
                    hashed_password=hash_password("demo12345"),
                    role=Role.ADMIN,
                )
            )
            log.info("created_demo_tenant", tenant_id=str(tenant.id))

        for title, body in SAMPLE_DOCS:
            await upsert_document(
                db,
                tenant_id=tenant.id,
                job_id=None,
                record=Record(external_id=title, content=body, metadata={"title": title}),
            )
        log.info("seeded_documents", count=len(SAMPLE_DOCS))

    print("Seed complete. Login: admin@demo.io / demo12345 (tenant slug: demo)")


if __name__ == "__main__":
    asyncio.run(main())
