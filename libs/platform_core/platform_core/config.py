"""Centralised, environment-driven configuration.

All services and workers import :func:`get_settings`. Values are sourced from
environment variables (12-factor), with ``.env`` support for local development.
Secrets in production are injected via Kubernetes Secrets mounted as env vars.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class EmbeddingProvider(StrEnum):
    LOCAL = "local"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- Core ----
    environment: Environment = Environment.LOCAL
    service_name: str = "gateway"
    log_level: str = "INFO"
    log_json: bool = True

    # ---- Database ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "platform"
    postgres_password: str = "platform"
    postgres_db: str = "platform"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ---- Redis / cache ----
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300

    # ---- Celery ----
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ---- Security ----
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    api_key_salt: str = "change-me-too"
    rate_limit_default: str = "100/minute"
    # Comma-separated list of allowed browser origins for the SPA frontend. "*"
    # is fine for local/dev; lock this down to the real host(s) in production.
    cors_origins: str = "*"

    # ---- AI / Embeddings ----
    embedding_provider: EmbeddingProvider = EmbeddingProvider.LOCAL
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    openai_api_key: str | None = None

    # ---- Object storage ----
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_bucket: str = "ingest"

    # ---- Observability ----
    otel_exporter_otlp_endpoint: str | None = "http://localhost:4317"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = 1.0
    elastic_apm_server_url: str | None = None
    elastic_apm_service_name: str = "data-platform"
    elastic_apm_environment: str = "local"
    prometheus_enabled: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Used by Alembic migrations which run synchronously."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Cache is process-local so each worker/replica reads its own env."""
    return Settings()
