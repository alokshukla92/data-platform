"""Retrieval service: semantic / keyword / hybrid search + context assembly API."""

from __future__ import annotations

from platform_core.app_factory import create_app
from platform_core.embeddings import get_embedding_provider
from platform_core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    default_rate_limit,
)

from .routers import search


async def _warm_model() -> None:
    # Pre-load the embedding model at startup so the first request isn't slow.
    import contextlib

    with contextlib.suppress(Exception):
        get_embedding_provider().embed(["warmup"])


app = create_app(service_name="retrieval", routers=[search.router], on_startup=_warm_model)
app.add_middleware(RateLimitMiddleware, limit=default_rate_limit(), window_seconds=60)
app.add_middleware(RequestContextMiddleware)
