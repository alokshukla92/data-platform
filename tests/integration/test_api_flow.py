"""End-to-end API flow against a live local stack.

Requires Postgres + Redis (``make up && make migrate``). Run with ``pytest -m integration``.
Exercises: tenant bootstrap -> login -> JWT -> ingest text -> poll job -> hybrid search.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

GATEWAY = "http://localhost:8000"
INGESTION = "http://localhost:8001"
RETRIEVAL = "http://localhost:8002"


@pytest.fixture(scope="module")
def slug() -> str:
    return f"it-{uuid.uuid4().hex[:8]}"


async def _wait_ready(url: str, tries: int = 20) -> None:
    async with httpx.AsyncClient() as c:
        for _ in range(tries):
            try:
                r = await c.get(f"{url}/health/ready", timeout=2)
                if r.status_code == 200 and r.json().get("ready"):
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    pytest.skip(f"service not ready: {url}")


async def test_full_ingest_and_search(slug: str):
    await _wait_ready(GATEWAY)
    await _wait_ready(INGESTION)
    await _wait_ready(RETRIEVAL)

    async with httpx.AsyncClient(timeout=30) as c:
        boot = await c.post(
            f"{GATEWAY}/api/v1/auth/bootstrap",
            json={
                "tenant_name": "IT",
                "tenant_slug": slug,
                "admin_email": f"{slug}@it.io",
                "admin_password": "password123",
            },
        )
        assert boot.status_code == 201, boot.text

        login = await c.post(
            f"{GATEWAY}/api/v1/auth/login",
            json={"email": f"{slug}@it.io", "password": "password123"},
        )
        token = login.json()["access_token"]
        headers = {"authorization": f"Bearer {token}"}

        up = await c.post(
            f"{INGESTION}/api/v1/ingest/text",
            headers=headers,
            json={"content": "ArgoCD reconciles cluster state from a git repository for GitOps."},
        )
        assert up.status_code == 202
        job_id = up.json()["job_id"]

        # Poll job until it leaves the pending/running state.
        for _ in range(30):
            jr = await c.get(f"{INGESTION}/api/v1/jobs/{job_id}", headers=headers)
            if jr.json()["status"] in ("succeeded", "failed", "dead_lettered"):
                break
            await asyncio.sleep(1)
        assert jr.json()["status"] == "succeeded"

        search = await c.post(
            f"{RETRIEVAL}/api/v1/search",
            headers=headers,
            json={"query": "what does argocd do", "mode": "hybrid", "top_k": 3},
        )
        assert search.status_code == 200
        assert len(search.json()["hits"]) >= 1
