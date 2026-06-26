"""Authentication + minimal tenant/user bootstrap endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from platform_core.auth_deps import require_role
from platform_core.config import get_settings
from platform_core.db import get_db
from platform_core.models import Role, Tenant, User
from platform_core.schemas import LoginRequest, Principal, TokenResponse
from platform_core.security import create_access_token, hash_password, verify_password
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class TenantBootstrap(BaseModel):
    tenant_name: str
    tenant_slug: str
    admin_email: EmailStr
    admin_password: str


@router.post("/bootstrap", status_code=201)
async def bootstrap_tenant(payload: TenantBootstrap, db: AsyncSession = Depends(get_db)) -> dict:
    """Create a tenant + initial admin. Idempotent on tenant slug."""
    existing = (
        await db.execute(select(Tenant).where(Tenant.slug == payload.tenant_slug))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant slug already exists")
    tenant = Tenant(name=payload.tenant_name, slug=payload.tenant_slug)
    db.add(tenant)
    await db.flush()
    admin = User(
        tenant_id=tenant.id,
        email=payload.admin_email,
        hashed_password=hash_password(payload.admin_password),
        role=Role.ADMIN,
    )
    db.add(admin)
    await db.flush()  # populate admin.id before returning
    return {"tenant_id": str(tenant.id), "admin_id": str(admin.id)}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == payload.email, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    settings = get_settings()
    token = create_access_token(subject=str(user.id), tenant_id=str(user.tenant_id), role=user.role)
    return TokenResponse(access_token=token, expires_in=settings.jwt_access_ttl_minutes * 60)


@router.get("/me", response_model=Principal)
async def me(principal: Principal = Depends(require_role(Role.VIEWER))) -> Principal:
    return principal


@router.post("/users", status_code=201)
async def create_user(
    email: EmailStr,
    password: str,
    role: Role = Role.VIEWER,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = User(
        tenant_id=uuid.UUID(principal.tenant_id),
        email=email,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.flush()
    return {"id": str(user.id), "email": email, "role": role.value}
