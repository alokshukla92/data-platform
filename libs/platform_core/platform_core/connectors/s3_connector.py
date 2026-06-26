"""AWS S3 connector (works against real S3, MinIO, or LocalStack via endpoint override).

Incremental sync lists objects with a stored continuation token / last key, and only
emits objects modified after the persisted ``last_modified`` watermark.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

from ..config import get_settings
from ..reliability import TransientError, with_breaker, with_retry
from .base import BaseConnector, Record, SyncResult
from .registry import register_connector


@register_connector("s3")
class S3Connector(BaseConnector):
    """Config keys: bucket, prefix, suffix (e.g. '.txt'), batch_size, endpoint_url,
    access_key_id, secret_access_key, region. Falls back to platform S3 settings.
    """

    def _client(self):
        import boto3

        s = get_settings()
        cfg = self.ctx.config
        return boto3.client(
            "s3",
            endpoint_url=cfg.get("endpoint_url", s.s3_endpoint_url),
            aws_access_key_id=cfg.get("access_key_id", s.s3_access_key_id),
            aws_secret_access_key=cfg.get("secret_access_key", s.s3_secret_access_key),
            region_name=cfg.get("region", s.s3_region),
        )

    async def validate(self) -> tuple[bool, str | None]:
        def _check() -> tuple[bool, str | None]:
            try:
                self._client().head_bucket(Bucket=self.ctx.config["bucket"])
                return True, "bucket reachable"
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)

        return await asyncio.to_thread(_check)

    @with_breaker("s3_connector")
    @with_retry(attempts=4)
    async def _list_page(self, token: str | None) -> dict:
        def _do() -> dict:
            cfg = self.ctx.config
            kwargs: dict = {
                "Bucket": cfg["bucket"],
                "Prefix": cfg.get("prefix", ""),
                "MaxKeys": int(cfg.get("batch_size", 100)),
            }
            if token:
                kwargs["ContinuationToken"] = token
            try:
                return self._client().list_objects_v2(**kwargs)
            except ConnectionError as exc:
                raise TransientError(str(exc)) from exc

        return await asyncio.to_thread(_do)

    async def _get_object(self, key: str) -> str:
        def _do() -> str:
            obj = self._client().get_object(Bucket=self.ctx.config["bucket"], Key=key)
            return obj["Body"].read().decode("utf-8", errors="replace")

        return await asyncio.to_thread(_do)

    async def fetch(self) -> AsyncIterator[SyncResult]:
        cfg = self.ctx.config
        suffix = cfg.get("suffix")
        watermark = self.ctx.cursor.get("last_modified")
        token = self.ctx.cursor.get("continuation_token")

        while True:
            await self.rate_limiter.acquire()
            page = await self._list_page(token)
            contents = page.get("Contents", [])
            records: list[Record] = []
            newest = watermark
            for obj in contents:
                key = obj["Key"]
                if suffix and not key.endswith(suffix):
                    continue
                lm: datetime = obj["LastModified"]
                lm_iso = lm.isoformat()
                if watermark and lm_iso <= watermark:
                    continue
                body = await self._get_object(key)
                records.append(
                    Record(
                        external_id=key,
                        content=body,
                        metadata={"size": obj.get("Size"), "last_modified": lm_iso},
                        source_uri=f"s3://{cfg['bucket']}/{key}",
                    )
                )
                newest = max(newest or lm_iso, lm_iso)
            token = page.get("NextContinuationToken")
            has_more = page.get("IsTruncated", False)
            yield SyncResult(
                records=records,
                next_cursor={"continuation_token": token, "last_modified": newest},
                has_more=has_more,
            )
            if not has_more:
                break
