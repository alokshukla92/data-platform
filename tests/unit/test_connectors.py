import httpx
import pytest
import respx
from platform_core.connectors import get_connector_class
from platform_core.connectors.base import ConnectorContext, RateLimiter

pytestmark = pytest.mark.unit

CSV_SAMPLE = "id,name,note\n1,alpha,first\n2,beta,second\n3,gamma,third\n"


async def test_csv_connector_validate_and_fetch():
    cls = get_connector_class("csv")
    ctx = ConnectorContext(
        tenant_id="t1",
        config={
            "raw": CSV_SAMPLE,
            "id_field": "id",
            "content_fields": ["name", "note"],
            "batch_size": 2,
        },
    )
    connector = cls(ctx)
    ok, _ = await connector.validate()
    assert ok

    batches = [b async for b in connector.fetch()]
    records = [r for b in batches for r in b.records]
    assert len(records) == 3
    assert records[0].external_id == "1"
    assert "alpha" in records[0].content
    # First batch advances the row_offset cursor for incremental resume.
    assert batches[0].next_cursor["row_offset"] == 2


async def test_csv_connector_incremental_resume():
    cls = get_connector_class("csv")
    ctx = ConnectorContext(
        tenant_id="t1",
        config={"raw": CSV_SAMPLE, "batch_size": 10},
        cursor={"row_offset": 2},  # resume after first two rows
    )
    records = []
    async for batch in cls(ctx).fetch():
        records.extend(batch.records)
    assert len(records) == 1


@respx.mock
async def test_rest_connector_pagination():
    base = "https://api.example.com"
    respx.get(f"{base}/items").mock(
        side_effect=[
            httpx.Response(
                200, json={"data": [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]}
            ),
            httpx.Response(200, json={"data": [{"id": 3, "content": "c"}]}),
        ]
    )
    cls = get_connector_class("rest")
    ctx = ConnectorContext(
        tenant_id="t1",
        config={
            "base_url": base,
            "path": "/items",
            "records_path": "data",
            "id_field": "id",
            "content_field": "content",
            "page_size": 2,
        },
    )
    records = []
    async for batch in cls(ctx).fetch():
        records.extend(batch.records)
    assert [r.external_id for r in records] == ["1", "2", "3"]


async def test_rate_limiter_smoke():
    rl = RateLimiter(rate_per_sec=1000, burst=5)
    for _ in range(5):
        await rl.acquire()  # should not raise / block meaningfully
