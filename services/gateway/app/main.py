"""Gateway service: authentication, tenant/user admin, API keys, connector management.

This is the public entrypoint for identity + configuration. Data-plane traffic (uploads,
search) is served by the ingestion and retrieval services, routed via the K8s Ingress.
"""

from __future__ import annotations

from platform_core.app_factory import create_app
from platform_core.middleware import (
    AuditMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    default_rate_limit,
)

from .routers import apikeys, auth, connectors

app = create_app(service_name="gateway", routers=[auth.router, apikeys.router, connectors.router])
# Middleware executes in reverse registration order: context -> rate limit -> audit.
app.add_middleware(AuditMiddleware)
app.add_middleware(RateLimitMiddleware, limit=default_rate_limit(), window_seconds=60)
app.add_middleware(RequestContextMiddleware)
