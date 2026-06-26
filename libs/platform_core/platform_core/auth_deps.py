"""FastAPI authentication & RBAC dependencies.

Supports two credential types:
  * Bearer JWT  (``Authorization: Bearer <token>``)
  * API key     (``X-API-Key: dpk_xxx.yyy``)

``require_role`` builds a dependency enforcing a minimum role using the role hierarchy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import ApiKey, Role
from .schemas import Principal
from .security import decode_access_token, role_allows, verify_api_key


async def get_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if x_api_key:
        return await _principal_from_api_key(x_api_key, db)
    if authorization and authorization.lower().startswith("bearer "):
        return _principal_from_jwt(authorization.split(" ", 1)[1])
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _principal_from_jwt(token: str) -> Principal:
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return Principal(
        subject=claims["sub"],
        tenant_id=claims["tid"],
        role=Role(claims["role"]),
        auth_method="jwt",
    )


async def _principal_from_api_key(raw_key: str, db: AsyncSession) -> Principal:
    prefix = raw_key.split(".", 1)[0]
    rows = (
        await db.execute(select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked.is_(False)))
    ).scalars()
    for key in rows:
        if verify_api_key(raw_key, key.hashed_key):
            key.last_used_at = datetime.now(UTC)
            return Principal(
                subject=f"apikey:{key.id}",
                tenant_id=str(key.tenant_id),
                role=key.role,
                auth_method="api_key",
            )
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")


def require_role(minimum: Role):
    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not role_allows(principal.role, minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Requires role >= {minimum.value}"
            )
        return principal

    return _dep
