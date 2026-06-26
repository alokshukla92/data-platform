"""Retrieval engine: semantic (pgvector), keyword (Postgres FTS), and hybrid search.

Hybrid search fuses normalised vector similarity and full-text rank with a tunable
``alpha`` weight, then optionally filters by JSONB metadata. Vector distance uses cosine
(``<=>``) which pairs with normalised embeddings.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import get_embedding_provider
from .schemas import SearchHit
from .telemetry import SEARCH_REQUESTS_TOTAL


def _metadata_clause(metadata_filter: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a JSONB metadata filter. Both keys and values are bound as parameters, so no
    user-supplied string is ever interpolated into the SQL (injection-safe)."""
    if not metadata_filter:
        return "", {}
    clauses, params = [], {}
    for i, (k, v) in enumerate(metadata_filter.items()):
        kparam, vparam = f"mf_k_{i}", f"mf_v_{i}"
        clauses.append(f"dc.chunk_metadata ->> :{kparam} = :{vparam}")
        params[kparam] = str(k)
        params[vparam] = str(v)
    return " AND " + " AND ".join(clauses), params


async def semantic_search(
    db: AsyncSession, *, tenant_id: str, query: str, top_k: int, metadata_filter: dict | None = None
) -> list[SearchHit]:
    SEARCH_REQUESTS_TOTAL.labels(mode="semantic").inc()
    vector = get_embedding_provider().embed([query])[0]
    mf_sql, mf_params = _metadata_clause(metadata_filter or {})
    stmt = text(
        f"""
        SELECT dc.id, dc.document_id, dc.content, dc.chunk_metadata,
               1 - (dc.embedding <=> :qvec) AS score
        FROM document_chunks dc
        WHERE dc.tenant_id = :tid AND dc.embedding IS NOT NULL {mf_sql}
        ORDER BY dc.embedding <=> :qvec ASC
        LIMIT :k
        """
    ).bindparams(bindparam("qvec", value=str(vector)))
    rows = (await db.execute(stmt, {"tid": tenant_id, "k": top_k, **mf_params})).mappings()
    return [_row_to_hit(r) for r in rows]


async def keyword_search(
    db: AsyncSession, *, tenant_id: str, query: str, top_k: int, metadata_filter: dict | None = None
) -> list[SearchHit]:
    SEARCH_REQUESTS_TOTAL.labels(mode="keyword").inc()
    mf_sql, mf_params = _metadata_clause(metadata_filter or {})
    stmt = text(
        f"""
        SELECT dc.id, dc.document_id, dc.content, dc.chunk_metadata,
               ts_rank(to_tsvector('english', dc.content),
                       plainto_tsquery('english', :q)) AS score
        FROM document_chunks dc
        WHERE dc.tenant_id = :tid
          AND to_tsvector('english', dc.content) @@ plainto_tsquery('english', :q) {mf_sql}
        ORDER BY score DESC
        LIMIT :k
        """
    )
    rows = (
        await db.execute(stmt, {"tid": tenant_id, "q": query, "k": top_k, **mf_params})
    ).mappings()
    return [_row_to_hit(r) for r in rows]


async def hybrid_search(
    db: AsyncSession,
    *,
    tenant_id: str,
    query: str,
    top_k: int,
    alpha: float = 0.5,
    metadata_filter: dict | None = None,
) -> list[SearchHit]:
    """Reciprocal-weighted fusion of semantic and keyword results."""
    SEARCH_REQUESTS_TOTAL.labels(mode="hybrid").inc()
    pool = max(top_k * 4, 20)
    sem = await semantic_search(
        db, tenant_id=tenant_id, query=query, top_k=pool, metadata_filter=metadata_filter
    )
    kw = await keyword_search(
        db, tenant_id=tenant_id, query=query, top_k=pool, metadata_filter=metadata_filter
    )
    scores: dict[uuid.UUID, float] = {}
    hit_by_id: dict[uuid.UUID, SearchHit] = {}
    for hits, weight in ((sem, alpha), (kw, 1 - alpha)):
        norm = _normalise([h.score for h in hits])
        for h, s in zip(hits, norm, strict=True):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + weight * s
            hit_by_id[h.chunk_id] = h
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    out = []
    for chunk_id, fused in ranked:
        hit = hit_by_id[chunk_id]
        out.append(hit.model_copy(update={"score": round(fused, 6)}))
    return out


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _row_to_hit(row) -> SearchHit:
    return SearchHit(
        chunk_id=row["id"],
        document_id=row["document_id"],
        content=row["content"],
        score=float(row["score"]),
        metadata=row["chunk_metadata"],
    )
