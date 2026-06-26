"""Upload + validation API.

Two ingestion modes:
  * ``/upload/file``  - multipart file (CSV/PDF/text). Validated, metadata extracted,
    persisted to object storage, then queued for async processing.
  * ``/upload/text``  - inline text payload (fast path for small content).

Idempotency: clients pass an ``Idempotency-Key`` header; duplicate submissions return the
original job instead of creating a new one.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from platform_core.auth_deps import require_role
from platform_core.db import get_db
from platform_core.models import IngestionJob, JobStatus, Role
from platform_core.schemas import Principal, UploadResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/ingest", tags=["ingestion"])

MAX_BYTES = 25 * 1024 * 1024  # 25 MiB upload cap (validation guard)
ALLOWED_SUFFIXES = {".csv", ".pdf", ".txt", ".md", ".json"}


class TextUpload(BaseModel):
    content: str
    title: str | None = None
    metadata: dict = {}


async def _get_or_create_job(
    db: AsyncSession, *, tenant_id: uuid.UUID, idem: str, source_uri: str, meta: dict
) -> tuple[IngestionJob, bool]:
    existing = (
        await db.execute(
            select(IngestionJob).where(
                IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == idem
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing, False
    job = IngestionJob(
        tenant_id=tenant_id,
        idempotency_key=idem,
        status=JobStatus.PENDING,
        source_uri=source_uri,
        job_metadata=meta,
    )
    db.add(job)
    await db.flush()
    return job, True


@router.post("/text", response_model=UploadResponse, status_code=202)
async def upload_text(
    payload: TextUpload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_role(Role.EDITOR)),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    if not payload.content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty content")
    tid = uuid.UUID(principal.tenant_id)
    idem = idempotency_key or hashlib.sha256(payload.content.encode()).hexdigest()
    meta = {"title": payload.title, "kind": "text", **payload.metadata}
    job, created = await _get_or_create_job(
        db, tenant_id=tid, idem=idem, source_uri=payload.title or "inline-text", meta=meta
    )
    if created:
        from workers.tasks import process_record

        process_record.delay(
            job_id=str(job.id),
            tenant_id=str(tid),
            record={
                "external_id": idem,
                "content": payload.content,
                "metadata": meta,
                "source_uri": payload.title,
            },
        )
    return UploadResponse(job_id=job.id, status=job.status, idempotency_key=idem)


@router.post("/file", response_model=UploadResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_role(Role.EDITOR)),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    suffix = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported type {suffix}")
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty file")

    tid = uuid.UUID(principal.tenant_id)
    digest = hashlib.sha256(raw).hexdigest()
    idem = idempotency_key or digest
    meta = {
        "title": title or file.filename,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(raw),
        "suffix": suffix,
    }
    job, created = await _get_or_create_job(
        db, tenant_id=tid, idem=idem, source_uri=file.filename or "upload", meta=meta
    )
    if created:
        await _enqueue_file(job_id=job.id, tenant_id=tid, raw=raw, suffix=suffix, meta=meta)
    return UploadResponse(job_id=job.id, status=job.status, idempotency_key=idem)


async def _enqueue_file(
    *, job_id: uuid.UUID, tenant_id: uuid.UUID, raw: bytes, suffix: str, meta: dict
) -> None:
    from workers.tasks import process_record

    if suffix == ".pdf":
        import base64

        from platform_core.connectors import get_connector_class
        from platform_core.connectors.base import ConnectorContext

        connector = get_connector_class("pdf")(
            ConnectorContext(
                tenant_id=str(tenant_id), config={"content_b64": base64.b64encode(raw).decode()}
            )
        )
        # Extract synchronously here (small files) then queue each page record.
        async for result in connector.fetch():
            for rec in result.records:
                process_record.delay(
                    job_id=str(job_id),
                    tenant_id=str(tenant_id),
                    record={
                        "external_id": rec.external_id,
                        "content": rec.content,
                        "metadata": {**meta, **rec.metadata},
                        "source_uri": rec.source_uri,
                    },
                )
        await connector.close()
    else:
        text_content = raw.decode("utf-8", errors="replace")
        process_record.delay(
            job_id=str(job_id),
            tenant_id=str(tenant_id),
            record={"external_id": meta["filename"], "content": text_content, "metadata": meta},
        )
