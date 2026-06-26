"""Initial schema: pgvector extension, core tables, and search indexes.

Creates the full baseline schema from the ORM metadata, then layers on the
specialised indexes that autogenerate cannot express:
  * HNSW index on document_chunks.embedding for fast approximate vector search
  * GIN index on a full-text vector of document_chunks.content for keyword search
  * partial index on active ingestion jobs to speed up the scheduler's scans

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import platform_core.models  # noqa: F401  (registers tables on Base.metadata)
from alembic import op
from platform_core.db import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Create all ORM-defined tables, indexes, and constraints.
    Base.metadata.create_all(bind=bind)

    # Approximate nearest-neighbour index (cosine) for semantic search.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Full-text search index for keyword / hybrid search.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunks_content_fts
        ON document_chunks USING gin (to_tsvector('english', content))
        """
    )

    # Speed up the scheduler scanning for active connectors / pending work.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_jobs_pending
        ON ingestion_jobs (created_at)
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_pending")
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_fts")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    Base.metadata.drop_all(bind=op.get_bind())
