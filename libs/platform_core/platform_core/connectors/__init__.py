"""Pluggable data connector framework.

Each connector subclasses :class:`BaseConnector` and is registered in the
:data:`registry`. Connectors are discovered by ``ConnectorType`` so the ingestion
pipeline and Celery workers can instantiate them generically from stored config.
"""

from .base import (
    BaseConnector,
    ConnectorContext,
    ConnectorError,
    RateLimiter,
    Record,
    SyncResult,
)
from .registry import get_connector_class, register_connector, registry

__all__ = [
    "BaseConnector",
    "ConnectorContext",
    "ConnectorError",
    "RateLimiter",
    "Record",
    "SyncResult",
    "registry",
    "register_connector",
    "get_connector_class",
]

# Import side-effects register the built-in connectors.
from . import (  # noqa: E402,F401
    csv_connector,
    pdf_connector,
    postgres_connector,
    rest_connector,
    s3_connector,
)
