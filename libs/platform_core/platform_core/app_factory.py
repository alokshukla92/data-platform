"""Shared FastAPI application factory.

Every service (gateway, ingestion, retrieval) builds its app from here so logging,
telemetry, metrics, health probes, and graceful shutdown behave identically.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .cache import close_redis, get_redis
from .config import get_settings
from .db import dispose_engine, init_engine, session_scope
from .logging import configure_logging, get_logger
from .telemetry import instrument_clients, instrument_fastapi, setup_telemetry

log = get_logger(__name__)

# Process-wide flag flipped during graceful shutdown so readiness starts failing,
# letting the load balancer drain traffic before the pod exits.
_shutting_down = False


def _build_health_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/live")
    async def liveness() -> dict[str, str]:
        """Liveness: process is up. Kubelet restarts the pod if this fails."""
        return {"status": "alive"}

    @router.get("/health/ready")
    async def readiness() -> dict[str, object]:
        """Readiness: dependencies reachable. Removed from Service endpoints if failing."""
        if _shutting_down:
            return {"status": "draining", "ready": False}
        checks: dict[str, bool] = {}
        try:
            await get_redis().ping()
            checks["redis"] = True
        except Exception:
            checks["redis"] = False
        try:
            async with session_scope() as s:
                await s.execute(__import__("sqlalchemy").text("SELECT 1"))
            checks["postgres"] = True
        except Exception:
            checks["postgres"] = False
        ready = all(checks.values())
        return {"status": "ready" if ready else "degraded", "ready": ready, "checks": checks}

    @router.get("/health/startup")
    async def startup() -> dict[str, str]:
        return {"status": "started"}

    return router


def create_app(
    *,
    service_name: str,
    routers: list[APIRouter] | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    settings = get_settings()
    configure_logging(
        service_name=service_name, level=settings.log_level, json_logs=settings.log_json
    )
    setup_telemetry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("service_starting", service=service_name, env=settings.environment.value)
        init_engine(settings)
        instrument_clients()
        if on_startup:
            await on_startup()
        yield
        # NOTE: we deliberately do NOT install our own SIGTERM/SIGINT handlers.
        # uvicorn already owns those signals; overriding them via
        # loop.add_signal_handler swallows the signal and prevents both graceful
        # shutdown and --reload. Kubernetes drains the load balancer via a
        # container preStop hook (see Helm deployment) before SIGTERM is sent, at
        # which point this lifespan-shutdown block flips readiness to draining.
        global _shutting_down
        _shutting_down = True
        log.info("service_draining", service=service_name)
        # Grace window: let in-flight requests finish and LB stop routing new traffic.
        await asyncio.sleep(1.0)
        if on_shutdown:
            await on_shutdown()
        await dispose_engine()
        await close_redis()
        log.info("service_stopped", service=service_name)

    app = FastAPI(
        title=f"data-platform :: {service_name}",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    if settings.prometheus_enabled:
        Instrumentator(excluded_handlers=["/metrics", "/health.*"]).instrument(app).expose(
            app, endpoint="/metrics", include_in_schema=False
        )
    instrument_fastapi(app)

    app.include_router(_build_health_router())
    for router in routers or []:
        app.include_router(router)
    return app
