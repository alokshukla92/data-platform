"""MySQL / MariaDB source connector. Pulls rows from an external MySQL-compatible DB.

Two modes:
  * single table  - set ``table`` (+ optional ``cursor_field``/``content_fields``).
  * whole database - omit ``table`` and every base table is synced. The primary-key
    column is auto-detected per table for keyset incremental sync; tables without a
    single-column PK fall back to OFFSET pagination (still incremental via the cursor).

The cursor is stored per table as ``{"tables": {"<name>": {"last_value": ...}}}`` so a
whole-database sync resumes each table independently on the next run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..reliability import TransientError, with_retry
from .base import BaseConnector, ConnectorError, Record, SyncResult
from .registry import register_connector


def _normalize_dsn(dsn: str) -> str:
    """Force the async aiomysql driver regardless of how the user wrote the scheme.

    Accepts ``mysql://``, ``mariadb://``, ``mysql+pymysql://`` etc. and rewrites them to
    ``mysql+aiomysql://`` so SQLAlchemy uses an async driver (otherwise it tries to import
    the sync ``MySQLdb`` and fails with "No module named 'MySQLdb'").
    """
    if "://" not in dsn:
        raise ConnectorError("mysql connector requires a DSN like mysql://user:pass@host/db")
    _, rest = dsn.split("://", 1)
    return f"mysql+aiomysql://{rest}"


@register_connector("mysql")
class MySQLConnector(BaseConnector):
    """Config keys: dsn, [table], [tables], [exclude_tables], [cursor_field],
    [content_fields], [batch_size]."""

    def _dsn(self) -> str:
        dsn = self.ctx.config.get("dsn")
        if not dsn:
            raise ConnectorError("mysql connector requires 'dsn'")
        return _normalize_dsn(dsn)

    async def validate(self) -> tuple[bool, str | None]:
        try:
            engine = create_async_engine(self._dsn(), pool_pre_ping=True)
            async with engine.connect() as conn:
                db = (await conn.execute(text("SELECT DATABASE()"))).scalar()
            await engine.dispose()
            if not db:
                return False, "connected, but the DSN has no database selected"
            return True, f"connection ok (database '{db}')"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def _list_tables(self, conn) -> list[str]:
        cfg = self.ctx.config
        if cfg.get("table"):
            return [cfg["table"]]
        if cfg.get("tables"):
            return list(cfg["tables"])
        rows = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        )
        tables = [r[0] for r in rows]
        exclude = set(cfg.get("exclude_tables", []))
        return [t for t in tables if t not in exclude]

    async def _primary_key(self, conn, table: str) -> str | None:
        """Single-column primary key for keyset pagination, or None."""
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.key_column_usage "
                    "WHERE table_schema = DATABASE() AND table_name = :t "
                    "AND constraint_name = 'PRIMARY' ORDER BY ordinal_position"
                ),
                {"t": table},
            )
        ).fetchall()
        return rows[0][0] if len(rows) == 1 else None

    @with_retry(attempts=4, retry_on=(TransientError,))
    async def _fetch_keyset(self, conn, table, key, last_value, limit) -> list[dict]:
        where = ""
        params: dict[str, Any] = {"lim": limit}
        if last_value is not None:
            where = f"WHERE `{key}` > :last "
            params["last"] = last_value
        stmt = text(
            f"SELECT * FROM `{table}` {where}"  # noqa: S608 - identifiers from tenant config
            f"ORDER BY `{key}` ASC LIMIT :lim"
        )
        try:
            return [dict(r._mapping) for r in await conn.execute(stmt, params)]
        except ConnectionError as exc:
            raise TransientError(str(exc)) from exc

    @with_retry(attempts=4, retry_on=(TransientError,))
    async def _fetch_offset(self, conn, table, offset, limit) -> list[dict]:
        stmt = text(
            f"SELECT * FROM `{table}` LIMIT :lim OFFSET :off"  # noqa: S608 - trusted identifier
        )
        try:
            rows = await conn.execute(stmt, {"lim": limit, "off": offset})
            return [dict(r._mapping) for r in rows]
        except ConnectionError as exc:
            raise TransientError(str(exc)) from exc

    def _to_record(self, table: str, row: dict, id_field: str | None, db: str) -> Record:
        cfg = self.ctx.config
        content_fields = cfg.get("content_fields")
        content = (
            " ".join(str(row.get(f, "")) for f in content_fields)
            if content_fields
            else " ".join(f"{k}: {v}" for k, v in row.items())
        )
        ext = f"{table}:{row.get(id_field)}" if id_field else f"{table}:{hash(frozenset(row))}"
        return Record(
            external_id=ext,
            content=content,
            metadata={"_table": table, **{k: str(v) for k, v in row.items()}},
            source_uri=f"mysql://{db}/{table}",
        )

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        batch_size = int(cfg.get("batch_size", 500))
        engine = create_async_engine(self._dsn(), pool_pre_ping=True)
        # Working copy of the per-table cursor; advanced and yielded each batch.
        cursor: dict[str, Any] = {"tables": dict(self.ctx.cursor.get("tables", {}))}
        try:
            async with engine.connect() as conn:
                db = (await conn.execute(text("SELECT DATABASE()"))).scalar()
                tables = await self._list_tables(conn)
                for table in tables:
                    key = cfg.get("cursor_field") or await self._primary_key(conn, table)
                    tstate = cursor["tables"].setdefault(table, {})
                    while True:
                        await self.rate_limiter.acquire()
                        if key:
                            last_value = tstate.get("last_value")
                            rows = await self._fetch_keyset(
                                conn, table, key, last_value, batch_size
                            )
                        else:
                            offset = int(tstate.get("offset", 0))
                            rows = await self._fetch_offset(conn, table, offset, batch_size)
                        if not rows:
                            break
                        records = [self._to_record(table, r, key, db) for r in rows]
                        if key:
                            tstate["last_value"] = rows[-1].get(key)
                        else:
                            tstate["offset"] = int(tstate.get("offset", 0)) + len(rows)
                        has_more = len(rows) == batch_size
                        yield SyncResult(
                            records=records,
                            next_cursor={"tables": dict(cursor["tables"])},
                            has_more=has_more or table != tables[-1],
                        )
                        if not has_more:
                            break
        finally:
            await engine.dispose()


# MariaDB speaks the MySQL wire protocol; reuse the same connector under its own type.
register_connector("mariadb")(MySQLConnector)
