"""Celery tasks: connector sync, record processing, embeddings, DLQ, periodic jobs.

Reliability model:
  * ``acks_late`` + idempotent processing => safe at-least-once semantics.
  * Automatic retries with exponential backoff for transient errors.
  * On terminal failure (max retries) the payload is parked on the ``dlq`` queue and the
    job row is marked ``dead_lettered`` for later inspection/replay.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from platform_core.connectors import get_connector_class
from platform_core.connectors.base import ConnectorContext, Record
from platform_core.db import session_scope
from platform_core.models import (
    ConnectorConfig,
    IngestionJob,
    JobStatus,
)
from platform_core.pipeline import record_event, upsert_document
from platform_core.telemetry import DLQ_DEPTH, INGEST_JOBS_TOTAL, JOB_PROCESSING_SECONDS
from sqlalchemy import select

from .celery_app import celery_app

log = get_task_logger(__name__)


_async_loop: asyncio.AbstractEventLoop | None = None
_async_loop_lock = threading.Lock()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    """A single, long-lived event loop shared by all worker threads.

    Celery's threads pool runs tasks on different OS threads. Using ``asyncio.run``
    per task would spin up a fresh loop each time, but our async SQLAlchemy engine +
    asyncpg pool are bound to the loop that created them; reusing that engine from a
    different loop raises "Future attached to a different loop". Funnelling every
    coroutine onto one dedicated background loop keeps the engine/pool valid and
    serialises DB access safely.
    """
    global _async_loop
    if _async_loop is None or _async_loop.is_closed():
        with _async_loop_lock:
            if _async_loop is None or _async_loop.is_closed():
                loop = asyncio.new_event_loop()
                threading.Thread(
                    target=loop.run_forever, name="worker-async-loop", daemon=True
                ).start()
                _async_loop = loop
    return _async_loop


def _run(coro):
    """Bridge Celery's sync worker to our async data layer (one shared loop)."""
    return asyncio.run_coroutine_threadsafe(coro, _get_async_loop()).result()


# --------------------------------------------------------------------------- connector sync
@shared_task(bind=True, name="workers.tasks.sync_connector", max_retries=5)
def sync_connector(self, job_id: str, connector_id: str) -> dict[str, Any]:
    try:
        return _run(_sync_connector_async(uuid.UUID(job_id), uuid.UUID(connector_id)))
    except Exception as exc:  # noqa: BLE001
        countdown = min(2**self.request.retries, 300)
        if self.request.retries >= self.max_retries:
            move_to_dlq.delay(job_id=job_id, reason=str(exc), task="sync_connector")
            _run(_mark_job(uuid.UUID(job_id), JobStatus.DEAD_LETTERED, error=str(exc)))
            return {"status": "dead_lettered", "error": str(exc)}
        _run(_mark_job(uuid.UUID(job_id), JobStatus.RETRYING, error=str(exc)))
        raise self.retry(exc=exc, countdown=countdown) from exc


async def _sync_connector_async(job_id: uuid.UUID, connector_id: uuid.UUID) -> dict[str, Any]:
    with JOB_PROCESSING_SECONDS.labels(job_type="sync_connector").time():
        async with session_scope() as db:
            cc = (
                await db.execute(select(ConnectorConfig).where(ConnectorConfig.id == connector_id))
            ).scalar_one()
            job = (
                await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
            ).scalar_one()
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            job.attempts += 1
            await record_event(db, job_id, JobStatus.RUNNING, "sync started")

            connector_cls = get_connector_class(cc.connector_type)
            ctx = ConnectorContext(tenant_id=str(cc.tenant_id), config=cc.config, cursor=cc.cursor)
            connector = connector_cls(ctx)

            total = 0
            async for result in connector.fetch():
                for rec in result.records:
                    await upsert_document(db, tenant_id=cc.tenant_id, job_id=job_id, record=rec)
                    total += 1
                cc.cursor = result.next_cursor  # persist incremental progress
                await db.flush()
            await connector.close()

            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)
            await record_event(db, job_id, JobStatus.SUCCEEDED, f"ingested {total} records")
    INGEST_JOBS_TOTAL.labels(connector_type=cc.connector_type, status="succeeded").inc()
    return {"status": "succeeded", "records": total}


# --------------------------------------------------------------------------- single record
@shared_task(bind=True, name="workers.tasks.process_record", max_retries=5)
def process_record(self, job_id: str, tenant_id: str, record: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run(_process_record_async(uuid.UUID(job_id), uuid.UUID(tenant_id), record))
    except Exception as exc:  # noqa: BLE001
        if self.request.retries >= self.max_retries:
            move_to_dlq.delay(job_id=job_id, reason=str(exc), task="process_record")
            _run(_mark_job(uuid.UUID(job_id), JobStatus.DEAD_LETTERED, error=str(exc)))
            return {"status": "dead_lettered"}
        raise self.retry(exc=exc, countdown=min(2**self.request.retries, 300)) from exc


async def _process_record_async(
    job_id: uuid.UUID, tenant_id: uuid.UUID, record: dict[str, Any]
) -> dict[str, Any]:
    with JOB_PROCESSING_SECONDS.labels(job_type="process_record").time():
        async with session_scope() as db:
            rec = Record(
                external_id=record.get("external_id", str(uuid.uuid4())),
                content=record["content"],
                metadata=record.get("metadata", {}),
                source_uri=record.get("source_uri"),
            )
            _, created = await upsert_document(db, tenant_id=tenant_id, job_id=job_id, record=rec)
            await _finalize_job(db, job_id)
    return {"status": "succeeded", "created": created}


# --------------------------------------------------------------------------- embeddings (explicit)
@shared_task(bind=True, name="workers.tasks.generate_embeddings", max_retries=3)
def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
    from platform_core.embeddings import get_embedding_provider

    try:
        return get_embedding_provider().embed(texts)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=min(2**self.request.retries, 60)) from exc


# --------------------------------------------------------------------------- DLQ
@shared_task(name="workers.tasks.move_to_dlq")
def move_to_dlq(job_id: str, reason: str, task: str) -> dict[str, Any]:
    log.error("moved_to_dlq", extra={"job_id": job_id, "reason": reason, "task": task})
    _run(_record_dlq_event(uuid.UUID(job_id), reason, task))
    return {"job_id": job_id, "parked": True}


@shared_task(name="workers.tasks.replay_dlq")
def replay_dlq(job_id: str, connector_id: str) -> dict[str, Any]:
    """Re-enqueue a dead-lettered job after the root cause is fixed."""
    _run(_mark_job(uuid.UUID(job_id), JobStatus.PENDING, error=None))
    sync_connector.delay(job_id=job_id, connector_id=connector_id)
    return {"job_id": job_id, "replayed": True}


# --------------------------------------------------------------------------- periodic
@shared_task(name="workers.tasks.scan_active_connectors")
def scan_active_connectors() -> dict[str, int]:
    return _run(_scan_active_connectors_async())


async def _scan_active_connectors_async() -> dict[str, int]:
    enqueued = 0
    async with session_scope() as db:
        connectors = (
            (await db.execute(select(ConnectorConfig).where(ConnectorConfig.is_active.is_(True))))
            .scalars()
            .all()
        )
        for cc in connectors:
            key = f"scheduled:{cc.id}:{datetime.now(UTC):%Y%m%d%H%M}"
            job = IngestionJob(
                tenant_id=cc.tenant_id,
                connector_id=cc.id,
                idempotency_key=key,
                status=JobStatus.PENDING,
                source_uri=cc.name,
            )
            db.add(job)
            await db.flush()
            sync_connector.delay(job_id=str(job.id), connector_id=str(cc.id))
            enqueued += 1
    return {"enqueued": enqueued}


@shared_task(name="workers.tasks.publish_dlq_metrics")
def publish_dlq_metrics() -> dict[str, int]:
    return _run(_publish_dlq_metrics_async())


async def _publish_dlq_metrics_async() -> dict[str, int]:
    async with session_scope() as db:
        from sqlalchemy import func

        count = (
            await db.execute(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.status == JobStatus.DEAD_LETTERED)
            )
        ).scalar_one()
    DLQ_DEPTH.labels(queue="dlq").set(count)
    return {"dlq_depth": int(count)}


# --------------------------------------------------------------------------- helpers
async def _mark_job(job_id: uuid.UUID, status: JobStatus, error: str | None) -> None:
    async with session_scope() as db:
        job = (
            await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            return
        job.status = status
        job.error = error
        if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.DEAD_LETTERED):
            job.finished_at = datetime.now(UTC)
        await record_event(db, job_id, status, error)


async def _finalize_job(db, job_id: uuid.UUID) -> None:
    job = (
        await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    ).scalar_one_or_none()
    if job and job.status != JobStatus.SUCCEEDED:
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        await record_event(db, job_id, JobStatus.SUCCEEDED, "record processed")


async def _record_dlq_event(job_id: uuid.UUID, reason: str, task: str) -> None:
    async with session_scope() as db:
        await record_event(db, job_id, JobStatus.DEAD_LETTERED, reason, task=task)


__all__ = ["celery_app"]
