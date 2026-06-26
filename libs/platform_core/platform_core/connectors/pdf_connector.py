"""PDF connector: extracts text per page from a file path or raw bytes.

Each page becomes one Record; incremental sync resumes from the last processed page.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from pathlib import Path

from .base import BaseConnector, ConnectorError, Record, SyncResult
from .registry import register_connector


@register_connector("pdf")
class PdfConnector(BaseConnector):
    """Config keys: path (file path) OR content_b64 (base64 bytes), pages_per_batch."""

    def _open_reader(self):
        from pypdf import PdfReader

        cfg = self.ctx.config
        if b64 := cfg.get("content_b64"):
            import base64

            return PdfReader(io.BytesIO(base64.b64decode(b64)))
        path = cfg.get("path")
        if not path or not Path(path).exists():
            raise ConnectorError(f"PDF path not found: {path}")
        return PdfReader(path)

    async def validate(self) -> tuple[bool, str | None]:
        try:
            reader = self._open_reader()
            return len(reader.pages) > 0, f"pages={len(reader.pages)}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        reader = self._open_reader()
        total = len(reader.pages)
        per_batch = int(cfg.get("pages_per_batch", 10))
        start = int(self.ctx.cursor.get("page", 0))

        page = start
        while page < total:
            await self.rate_limiter.acquire()
            records = []
            for p in range(page, min(page + per_batch, total)):
                text = reader.pages[p].extract_text() or ""
                if text.strip():
                    records.append(
                        Record(
                            external_id=f"page-{p}",
                            content=text,
                            metadata={"page": p, "total_pages": total},
                            source_uri=cfg.get("path"),
                        )
                    )
            page += per_batch
            yield SyncResult(records=records, next_cursor={"page": page}, has_more=page < total)
