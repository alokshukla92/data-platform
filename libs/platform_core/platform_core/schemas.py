"""Pydantic v2 API schemas shared across services."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import ConnectorType, JobStatus, Role

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- pagination
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


# --------------------------------------------------------------------------- auth
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Principal(BaseModel):
    """Authenticated identity attached to a request (from JWT or API key)."""

    subject: str
    tenant_id: str
    role: Role
    auth_method: str = "jwt"


class ApiKeyCreate(BaseModel):
    name: str
    role: Role = Role.VIEWER


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    api_key: str = Field(description="Shown once; store it securely")
    prefix: str
    role: Role


# --------------------------------------------------------------------------- connectors
class ConnectorCreate(BaseModel):
    name: str
    connector_type: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorOut(ORMModel):
    id: uuid.UUID
    name: str
    connector_type: ConnectorType
    is_active: bool
    cursor: dict[str, Any]
    created_at: datetime


class ConnectorValidationResult(BaseModel):
    ok: bool
    detail: str | None = None


# --------------------------------------------------------------------------- ingestion
class UploadResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    idempotency_key: str


class JobOut(ORMModel):
    id: uuid.UUID
    status: JobStatus
    source_uri: str | None
    attempts: int
    max_attempts: int
    error: str | None
    job_metadata: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobEventOut(ORMModel):
    status: JobStatus
    message: str | None
    event_metadata: dict[str, Any]
    created_at: datetime


# --------------------------------------------------------------------------- search / AI
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str = Field(default="hybrid", pattern="^(semantic|keyword|hybrid)$")
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    alpha: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Hybrid weight: vector vs keyword"
    )


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    mode: str
    hits: list[SearchHit]


class ContextResponse(BaseModel):
    query: str
    context: str
    citations: list[SearchHit]
