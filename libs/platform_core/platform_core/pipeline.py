"""Ingestion processing pipeline: records -> documents -> chunks -> embeddings.

Idempotent by design: documents are keyed by ``(tenant_id, content_hash)`` so reprocessing
the same content is a no-op upsert, which makes worker retries safe.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .connectors.base import Record
from .embeddings import EmbeddingProvider, get_embedding_provider
from .logging import get_logger
from .models import Document, DocumentChunk, JobEvent, JobStatus
from .text import chunk_text, content_hash, estimate_tokens

log = get_logger(__name__)


async def record_event(
    db: AsyncSession, job_id: uuid.UUID, status: JobStatus, message: str | None = None, **meta
) -> None:
    db.add(JobEvent(job_id=job_id, status=status, message=message, event_metadata=meta))


async def upsert_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID | None,
    record: Record,
    provider: EmbeddingProvider | None = None,
    chunk_size: int = 800,
    overlap: int = 120,
) -> tuple[Document, bool]:
    """Create or fetch a document and (re)generate its chunk embeddings.

    Returns ``(document, created)``. If a document with the same content hash already
    exists for the tenant, it is returned untouched (idempotency).
    """
    provider = provider or get_embedding_provider()
    chash = content_hash(record.content)

    existing = (
        await db.execute(
            select(Document).where(
                Document.tenant_id == tenant_id, Document.content_hash == chash
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    doc = Document(
        tenant_id=tenant_id,
        job_id=job_id,
        source_uri=record.source_uri,
        title=record.metadata.get("title") or (record.external_id if record.external_id else None),
        content_hash=chash,
        doc_metadata=record.metadata,
    )
    db.add(doc)
    await db.flush()  # assign doc.id

    chunks = chunk_text(record.content, chunk_size=chunk_size, overlap=overlap)
    if chunks:
        vectors = provider.embed(chunks)
        for idx, (text_chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=doc.id,
                    chunk_index=idx,
                    content=text_chunk,
                    embedding=vector,
                    token_count=estimate_tokens(text_chunk),
                    chunk_metadata={"source_uri": record.source_uri, **record.metadata},
                )
            )
    log.info("document_ingested", document_id=str(doc.id), chunks=len(chunks))
    return doc, True
