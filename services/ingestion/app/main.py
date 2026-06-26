"""Ingestion service: upload API, validation, metadata extraction, job tracking."""

from __future__ import annotations

from platform_core.app_factory import create_app
from platform_core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    default_rate_limit,
)

from .routers import jobs, upload

app = create_app(service_name="ingestion", routers=[upload.router, jobs.router])
app.add_middleware(RateLimitMiddleware, limit=default_rate_limit(), window_seconds=60)
app.add_middleware(RequestContextMiddleware)
