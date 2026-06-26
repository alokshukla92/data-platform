"""Connector base classes and shared primitives.

Every connector supports the four cross-cutting requirements:
  * incremental sync  -> via a persisted ``cursor`` (offset/timestamp/etag)
  * retry handling    -> via :func:`platform_core.reliability.with_retry`
  * rate limiting      -> via :class:`RateLimiter` (token bucket)
  * connection validation -> via :meth:`BaseConnector.validate`
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


class ConnectorError(Exception):
    """Base error for all connector failures."""


@dataclass
class Record:
    """A single unit pulled from a source, normalised for the ingestion pipeline."""

    external_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_uri: str | None = None


@dataclass
class SyncResult:
    records: list[Record]
    next_cursor: dict[str, Any]
    has_more: bool = False


@dataclass
class ConnectorContext:
    """Runtime context handed to a connector: its config + last-known sync cursor."""

    tenant_id: str
    config: dict[str, Any]
    cursor: dict[str, Any] = field(default_factory=dict)


class RateLimiter:
    """Asyncio token-bucket rate limiter (requests per second)."""

    def __init__(self, rate_per_sec: float, burst: int | None = None) -> None:
        self.rate = max(rate_per_sec, 0.001)
        self.capacity = burst or max(int(rate_per_sec), 1)
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens < 1:
                await asyncio.sleep((1 - self._tokens) / self.rate)
                self._tokens = 0
            else:
                self._tokens -= 1


class BaseConnector(ABC):
    connector_type: str

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        rate = float(ctx.config.get("rate_limit_per_sec", 10))
        self.rate_limiter = RateLimiter(rate)

    @abstractmethod
    async def validate(self) -> tuple[bool, str | None]:
        """Cheaply confirm the source is reachable and credentials/config are valid."""

    @abstractmethod
    def fetch(self) -> AsyncIterator[SyncResult]:
        """Yield batches of records, advancing the incremental cursor each batch."""

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None
