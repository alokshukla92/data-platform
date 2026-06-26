"""Cross-cutting HTTP middleware: request id, rate limiting, audit logging."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .cache import get_redis
from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id + basic context to structlog for every log line in the request."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("method", "path")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Distributed fixed-window rate limiter backed by Redis (per client IP).

    Fail-open: if Redis is unavailable we allow the request rather than hard-failing the API.
    """

    def __init__(self, app, limit: int = 100, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith(("/health", "/metrics")):
            return await call_next(request)
        client_ip = request.client.host if request.client else "anon"
        identity = request.headers.get("x-api-key") or client_ip
        bucket = int(time.time()) // self.window
        key = f"ratelimit:{identity}:{bucket}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.window)
            if count > self.limit:
                return JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(self.window)},
                )
        except Exception:  # noqa: BLE001 - fail open on limiter outage
            log.warning("rate_limit_unavailable")
        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """Persist an audit trail for state-changing requests.

    Writes an :class:`~platform_core.models.AuditLog` row for non-idempotent methods
    (POST/PUT/PATCH/DELETE) capturing actor, action, status, latency and client IP.
    Failures here never block the request (audit is best-effort, logged on error).
    """

    AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        if request.method not in self.AUDITED_METHODS or request.url.path.startswith(
            ("/health", "/metrics")
        ):
            return response
        try:
            from .db import session_scope
            from .models import AuditLog

            async with session_scope() as db:
                db.add(
                    AuditLog(
                        actor=request.headers.get("x-api-key", "")[:24] or "anonymous",
                        action=f"{request.method} {request.url.path}",
                        resource=request.url.path,
                        ip=request.client.host if request.client else None,
                        status_code=response.status_code,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        details={"query": str(request.url.query)[:512]},
                    )
                )
        except Exception:  # noqa: BLE001 - audit must never break the request path
            log.warning("audit_write_failed", path=request.url.path)
        return response


def default_rate_limit() -> int:
    raw = get_settings().rate_limit_default  # e.g. "100/minute"
    try:
        return int(raw.split("/")[0])
    except (ValueError, IndexError):
        return 100
