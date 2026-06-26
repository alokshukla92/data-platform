"""API key issuance + revocation (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from platform_core.auth_deps import require_role
from platform_core.db import get_db
from platform_core.models import ApiKey, Role
from platform_core.schemas import ApiKeyCreate, ApiKeyCreated, Principal
from platform_core.security import generate_api_key
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(
    payload: ApiKeyCreate,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreated:
    full_key, prefix, hashed = generate_api_key()
    key = ApiKey(
        tenant_id=uuid.UUID(principal.tenant_id),
        name=payload.name,
        prefix=prefix,
        hashed_key=hashed,
        role=payload.role,
    )
    db.add(key)
    await db.flush()
    return ApiKeyCreated(
        id=key.id, name=key.name, api_key=full_key, prefix=prefix, role=key.role
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id, ApiKey.tenant_id == uuid.UUID(principal.tenant_id)
            )
        )
    ).scalar_one_or_none()
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.revoked = True
