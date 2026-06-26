"""Connector registry: maps ConnectorType -> connector class."""

from __future__ import annotations

from .base import BaseConnector

registry: dict[str, type[BaseConnector]] = {}


def register_connector(connector_type: str):
    def decorator(cls: type[BaseConnector]) -> type[BaseConnector]:
        cls.connector_type = connector_type
        registry[connector_type] = cls
        return cls

    return decorator


def get_connector_class(connector_type: str) -> type[BaseConnector]:
    try:
        return registry[connector_type]
    except KeyError as exc:
        raise KeyError(f"No connector registered for type '{connector_type}'") from exc
