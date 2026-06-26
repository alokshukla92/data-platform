"""PostgreSQL source connector. Pulls rows from an external Postgres database.

Incremental sync uses a monotonic cursor column (e.g. ``updated_at`` or ``id``) so each
run only reads rows newer than the last seen value. Keyset pagination avoids OFFSET cost.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..reliability import TransientError, with_retry
from .base import BaseConnector, ConnectorError, Record, SyncResult
from .registry import register_connector


@register_connector("postgres")
class PostgresConnector(BaseConnector):
    """Config keys: dsn, table, id_field, cursor_field, content_fields (list), batch_size."""

    def _dsn(self) -> str:
        dsn = self.ctx.config.get("dsn")
        if not dsn:
            raise ConnectorError("postgres connector requires 'dsn'")
        return dsn

    async def validate(self) -> tuple[bool, str | None]:
        try:
            engine = create_async_engine(self._dsn(), pool_pre_ping=True)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return True, "connection ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    @with_retry(attempts=4, retry_on=(TransientError,))
    async def _fetch_batch(self, engine, last_value: Any, batch_size: int) -> list[dict]:
        cfg = self.ctx.config
        cursor_field = cfg["cursor_field"]
        table = cfg["table"]
        # Build the keyset predicate only when we have a cursor. Binding NULL into
        # ``:last IS NULL OR col > :last`` makes asyncpg unable to infer the parameter
        # type (AmbiguousParameterError), so the first (full) sync omits it entirely.
        params: dict[str, Any] = {"lim": batch_size}
        where = ""
        if last_value is not None:
            where = f"WHERE {cursor_field} > :last "
            params["last"] = last_value
        try:
            async with engine.connect() as conn:
                stmt = text(
                    f"SELECT * FROM {table} "  # noqa: S608 - table from trusted tenant config
                    f"{where}"
                    f"ORDER BY {cursor_field} ASC LIMIT :lim"
                )
                result = await conn.execute(stmt, params)
                return [dict(r._mapping) for r in result]
        except ConnectionError as exc:
            raise TransientError(str(exc)) from exc

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        engine = create_async_engine(self._dsn(), pool_pre_ping=True)
        cursor_field = cfg["cursor_field"]
        id_field = cfg.get("id_field", cursor_field)
        content_fields = cfg.get("content_fields")
        batch_size = int(cfg.get("batch_size", 500))
        last_value = self.ctx.cursor.get("last_value")
        try:
            while True:
                await self.rate_limiter.acquire()
                rows = await self._fetch_batch(engine, last_value, batch_size)
                if not rows:
                    break
                records = []
                for row in rows:
                    content = (
                        " ".join(str(row.get(f, "")) for f in content_fields)
                        if content_fields
                        else " ".join(f"{k}: {v}" for k, v in row.items())
                    )
                    records.append(
                        Record(
                            external_id=str(row.get(id_field)),
                            content=content,
                            metadata={k: str(v) for k, v in row.items()},
                            source_uri=f"postgres://{cfg['table']}",
                        )
                    )
                last_value = rows[-1].get(cursor_field)
                has_more = len(rows) == batch_size
                yield SyncResult(
                    records=records,
                    next_cursor={"last_value": last_value},
                    has_more=has_more,
                )
                if not has_more:
                    break
        finally:
            await engine.dispose()
