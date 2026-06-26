"""Connector configuration CRUD + connection validation + manual sync trigger."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from platform_core.auth_deps import require_role
from platform_core.connectors import get_connector_class
from platform_core.connectors.base import ConnectorContext
from platform_core.db import get_db
from platform_core.models import ConnectorConfig, IngestionJob, JobStatus, Role
from platform_core.schemas import (
    ConnectorCreate,
    ConnectorOut,
    ConnectorValidationResult,
    Page,
    Principal,
    UploadResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


@router.post("", response_model=ConnectorOut, status_code=201)
async def create_connector(
    payload: ConnectorCreate,
    principal: Principal = Depends(require_role(Role.EDITOR)),
    db: AsyncSession = Depends(get_db),
) -> ConnectorOut:
    if payload.connector_type.value not in __import__(
        "platform_core.connectors", fromlist=["registry"]
    ).registry:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported connector type")
    cc = ConnectorConfig(
        tenant_id=uuid.UUID(principal.tenant_id),
        name=payload.name,
        connector_type=payload.connector_type,
        config=payload.config,
    )
    db.add(cc)
    await db.flush()
    return ConnectorOut.model_validate(cc)


@router.get("", response_model=Page[ConnectorOut])
async def list_connectors(
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> Page[ConnectorOut]:
    from sqlalchemy import func

    tid = uuid.UUID(principal.tenant_id)
    total = (
        await db.execute(
            select(func.count())
            .select_from(ConnectorConfig)
            .where(ConnectorConfig.tenant_id == tid)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(ConnectorConfig)
            .where(ConnectorConfig.tenant_id == tid)
            .order_by(ConnectorConfig.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    ).scalars().all()
    return Page(
        items=[ConnectorOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


async def _get_owned(db: AsyncSession, connector_id: uuid.UUID, tenant_id: str) -> ConnectorConfig:
    cc = (
        await db.execute(
            select(ConnectorConfig).where(
                ConnectorConfig.id == connector_id,
                ConnectorConfig.tenant_id == uuid.UUID(tenant_id),
            )
        )
    ).scalar_one_or_none()
    if not cc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector not found")
    return cc


@router.post("/{connector_id}/validate", response_model=ConnectorValidationResult)
async def validate_connector(
    connector_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.EDITOR)),
    db: AsyncSession = Depends(get_db),
) -> ConnectorValidationResult:
    cc = await _get_owned(db, connector_id, principal.tenant_id)
    connector = get_connector_class(cc.connector_type)(
        ConnectorContext(tenant_id=str(cc.tenant_id), config=cc.config, cursor=cc.cursor)
    )
    ok, detail = await connector.validate()
    await connector.close()
    return ConnectorValidationResult(ok=ok, detail=detail)


@router.post("/{connector_id}/sync", response_model=UploadResponse, status_code=202)
async def trigger_sync(
    connector_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.EDITOR)),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    cc = await _get_owned(db, connector_id, principal.tenant_id)
    idem = f"manual:{connector_id}:{uuid.uuid4().hex[:8]}"
    job = IngestionJob(
        tenant_id=cc.tenant_id,
        connector_id=cc.id,
        idempotency_key=idem,
        status=JobStatus.PENDING,
        source_uri=cc.name,
    )
    db.add(job)
    await db.flush()
    # Late import avoids a hard dependency on the broker when the gateway boots.
    from workers.tasks import sync_connector

    sync_connector.delay(job_id=str(job.id), connector_id=str(cc.id))
    return UploadResponse(job_id=job.id, status=job.status, idempotency_key=idem)
