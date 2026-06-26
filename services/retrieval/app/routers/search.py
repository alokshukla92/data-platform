"""Search + context retrieval endpoints with Redis caching."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from platform_core.auth_deps import require_role
from platform_core.cache import cache_get, cache_set
from platform_core.db import get_db
from platform_core.models import Role
from platform_core.schemas import (
    ContextResponse,
    Principal,
    SearchRequest,
    SearchResponse,
)
from platform_core.search import hybrid_search, keyword_search, semantic_search
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/search", tags=["search"])


async def _dispatch(db: AsyncSession, tenant_id: str, req: SearchRequest):
    common = {
        "tenant_id": tenant_id,
        "query": req.query,
        "top_k": req.top_k,
        "metadata_filter": req.metadata_filter,
    }
    if req.mode == "semantic":
        return await semantic_search(db, **common)
    if req.mode == "keyword":
        return await keyword_search(db, **common)
    return await hybrid_search(db, alpha=req.alpha, **common)


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    cache_key_parts = (
        principal.tenant_id,
        req.mode,
        req.query,
        req.top_k,
        req.alpha,
        str(sorted(req.metadata_filter.items())),
    )
    # Cache-aside: search results are read-heavy and tolerate short staleness.
    cached_hits = await cache_get("search", *cache_key_parts)
    if cached_hits is not None:
        return SearchResponse(query=req.query, mode=req.mode, hits=cached_hits)

    hits = await _dispatch(db, principal.tenant_id, req)
    payload = [h.model_dump() for h in hits]
    await cache_set("search", payload, *cache_key_parts, ttl=120)
    return SearchResponse(query=req.query, mode=req.mode, hits=hits)


@router.post("/context", response_model=ContextResponse)
async def context(
    req: SearchRequest,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> ContextResponse:
    """Assemble a single context window (for RAG/LLM prompts) from the top hits."""
    hits = await _dispatch(db, principal.tenant_id, req)
    blocks = [f"[{i + 1}] {h.content}" for i, h in enumerate(hits)]
    return ContextResponse(
        query=req.query, context="\n\n".join(blocks), citations=hits
    )
