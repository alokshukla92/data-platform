"""Job tracking + processing history API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from platform_core.auth_deps import require_role
from platform_core.db import get_db
from platform_core.models import IngestionJob, JobEvent, JobStatus, Role
from platform_core.schemas import JobEventOut, JobOut, Page, Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobOut])
async def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> Page[JobOut]:
    tid = uuid.UUID(principal.tenant_id)
    conditions = [IngestionJob.tenant_id == tid]
    if status_filter:
        conditions.append(IngestionJob.status == status_filter)
    total = (
        await db.execute(select(func.count()).select_from(IngestionJob).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(IngestionJob)
                .where(*conditions)
                .order_by(IngestionJob.created_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[JobOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    job = (
        await db.execute(
            select(IngestionJob).where(
                IngestionJob.id == job_id,
                IngestionJob.tenant_id == uuid.UUID(principal.tenant_id),
            )
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobOut.model_validate(job)


@router.get("/{job_id}/history", response_model=list[JobEventOut])
async def job_history(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[JobEventOut]:
    # Ensure the job belongs to the caller's tenant before returning history.
    owns = (
        await db.execute(
            select(IngestionJob.id).where(
                IngestionJob.id == job_id,
                IngestionJob.tenant_id == uuid.UUID(principal.tenant_id),
            )
        )
    ).scalar_one_or_none()
    if not owns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    events = (
        (
            await db.execute(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [JobEventOut.model_validate(e) for e in events]
