"""CSV connector. Reads from a local/mounted path or an in-memory buffer.

Incremental sync is row-offset based so re-runs resume after the last processed row.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from pathlib import Path

from .base import BaseConnector, ConnectorError, Record, SyncResult
from .registry import register_connector


@register_connector("csv")
class CsvConnector(BaseConnector):
    """Config keys: path (file path) OR raw (csv text), id_field, content_fields (list),
    delimiter, batch_size.
    """

    def _read_text(self) -> str:
        cfg = self.ctx.config
        if raw := cfg.get("raw"):
            return raw
        path = cfg.get("path")
        if not path or not Path(path).exists():
            raise ConnectorError(f"CSV path not found: {path}")
        return Path(path).read_text(encoding=cfg.get("encoding", "utf-8"))

    async def validate(self) -> tuple[bool, str | None]:
        try:
            text = self._read_text()
            reader = csv.reader(io.StringIO(text), delimiter=self.ctx.config.get("delimiter", ","))
            header = next(reader, None)
            return bool(header), f"columns={header}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        text = self._read_text()
        reader = csv.DictReader(io.StringIO(text), delimiter=cfg.get("delimiter", ","))
        rows = list(reader)
        start = int(self.ctx.cursor.get("row_offset", 0))
        batch_size = int(cfg.get("batch_size", 500))
        id_field = cfg.get("id_field")
        content_fields = cfg.get("content_fields")

        offset = start
        while offset < len(rows):
            await self.rate_limiter.acquire()
            batch = rows[offset : offset + batch_size]
            records = []
            for i, row in enumerate(batch, start=offset):
                if content_fields:
                    content = " ".join(str(row.get(f, "")) for f in content_fields)
                else:
                    content = " ".join(f"{k}: {v}" for k, v in row.items())
                records.append(
                    Record(
                        external_id=str(row.get(id_field, i)) if id_field else str(i),
                        content=content,
                        metadata=dict(row),
                        source_uri=cfg.get("path"),
                    )
                )
            offset += batch_size
            yield SyncResult(
                records=records,
                next_cursor={"row_offset": offset},
                has_more=offset < len(rows),
            )
