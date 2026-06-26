"""REST API connector with pagination, incremental sync, retry and rate limiting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..reliability import TransientError, with_breaker, with_retry
from .base import BaseConnector, ConnectorError, Record, SyncResult
from .registry import register_connector


@register_connector("rest")
class RestConnector(BaseConnector):
    """Config keys:
    base_url, path, method, headers, params, auth_token, page_param, size_param,
    page_size, records_path (dot-path to list), id_field, content_field,
    cursor_param (query param used for incremental sync), cursor_field (response field).
    """

    def _client(self) -> httpx.AsyncClient:
        cfg = self.ctx.config
        headers = dict(cfg.get("headers", {}))
        if token := cfg.get("auth_token"):
            headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(
            base_url=cfg["base_url"], headers=headers, timeout=httpx.Timeout(15.0)
        )

    async def validate(self) -> tuple[bool, str | None]:
        try:
            async with self._client() as client:
                resp = await client.request(
                    self.ctx.config.get("method", "GET"),
                    self.ctx.config.get("path", "/"),
                    params=self.ctx.config.get("params"),
                )
                return resp.status_code < 500, f"status={resp.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)

    @with_breaker("rest_connector")
    @with_retry(attempts=4)
    async def _request(self, client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
        await self.rate_limiter.acquire()
        resp = await client.request(
            self.ctx.config.get("method", "GET"), self.ctx.config.get("path", "/"), params=params
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientError(f"retryable status {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _dig(obj: Any, dotted: str | None) -> Any:
        if not dotted:
            return obj
        for part in dotted.split("."):
            obj = obj[part]
        return obj

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        page = int(self.ctx.cursor.get("page", cfg.get("start_page", 1)))
        last_cursor = self.ctx.cursor.get("cursor_value")
        size = int(cfg.get("page_size", 100))
        async with self._client() as client:
            while True:
                params = dict(cfg.get("params", {}))
                params[cfg.get("page_param", "page")] = page
                params[cfg.get("size_param", "size")] = size
                if (cp := cfg.get("cursor_param")) and last_cursor is not None:
                    params[cp] = last_cursor
                payload = await self._request(client, params)
                rows = self._dig(payload, cfg.get("records_path"))
                if not isinstance(rows, list):
                    raise ConnectorError("records_path did not resolve to a list")
                records = [
                    Record(
                        external_id=str(r.get(cfg.get("id_field", "id"))),
                        content=str(r.get(cfg.get("content_field", "content"), "")),
                        metadata=r,
                        source_uri=f"{cfg['base_url']}{cfg.get('path', '/')}#{page}",
                    )
                    for r in rows
                ]
                has_more = len(rows) == size
                if cf := cfg.get("cursor_field"):
                    last_cursor = rows[-1].get(cf) if rows else last_cursor
                page += 1
                yield SyncResult(
                    records=records,
                    next_cursor={"page": page, "cursor_value": last_cursor},
                    has_more=has_more,
                )
                if not has_more:
                    break
