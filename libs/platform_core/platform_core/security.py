"""Security primitives: password hashing, JWT issue/verify, API-key hashing, RBAC.

- Passwords: Argon2 (memory-hard) via passlib.
- JWT: short-lived HS256 access tokens carrying tenant + role claims.
- API keys: random token shown once; only a salted hash is stored.
- RBAC: simple role hierarchy (admin > editor > viewer) enforced by FastAPI deps.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from .config import Settings, get_settings
from .models import Role

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")

_ROLE_RANK = {Role.VIEWER: 0, Role.EDITOR: 1, Role.ADMIN: 2}


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


# --------------------------------------------------------------------------- JWT
def create_access_token(
    *, subject: str, tenant_id: str, role: Role | str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    # The ORM may hand us a plain string for the role; normalise to the enum.
    role = role if isinstance(role, Role) else Role(role)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "tid": tenant_id,
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# --------------------------------------------------------------------------- API keys
def generate_api_key() -> tuple[str, str, str]:
    """Return ``(full_key, prefix, hashed_key)``. Show ``full_key`` once, store the rest."""
    prefix = "dpk_" + secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full_key = f"{prefix}.{secret}"
    return full_key, prefix, hash_api_key(full_key)


def hash_api_key(full_key: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return hmac.new(settings.api_key_salt.encode(), full_key.encode(), hashlib.sha256).hexdigest()


def verify_api_key(full_key: str, hashed: str, settings: Settings | None = None) -> bool:
    return hmac.compare_digest(hash_api_key(full_key, settings), hashed)


# --------------------------------------------------------------------------- RBAC
def role_allows(actual: Role | str, required: Role | str) -> bool:
    actual = actual if isinstance(actual, Role) else Role(actual)
    required = required if isinstance(required, Role) else Role(required)
    return _ROLE_RANK[actual] >= _ROLE_RANK[required]
