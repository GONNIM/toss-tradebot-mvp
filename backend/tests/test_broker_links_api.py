"""1025-06 · /api/v1/broker-links (공개 읽기 · 관리자 수정)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TOKEN = "broker_links_test_token_32chars_00"


@pytest.fixture
async def client(monkeypatch):
    from backend.services.db import get_session, init_db
    from backend.services.models import TossStockCode

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        await s.execute(delete(TossStockCode))
        s.add(TossStockCode(symbol="WEN", toss_code="US19810527001", source="api", verified=False))
        s.add(TossStockCode(symbol="AAPL", toss_code="US19801212001", source="manual", verified=True))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_public_reads_table_only(client, monkeypatch):
    from backend.execution.brokers import toss_client

    monkeypatch.setattr(toss_client, "get_toss_client", lambda: pytest.fail("공개 API 는 토스를 부르면 안 됨"))
    r = await client.get("/api/v1/broker-links", params={"symbols": "aapl,WEN,005930,MRNA"})
    assert r.status_code == 200
    links = {x["symbol"]: x for x in r.json()["links"]}
    assert links["AAPL"]["url"] == "https://www.tossinvest.com/stocks/US19801212001/order"
    assert links["WEN"]["kind"] == "search"  # 확인 전
    assert links["005930"]["url"] == "https://www.tossinvest.com/stocks/A005930/order"
    assert links["MRNA"]["kind"] == "search"


@pytest.mark.asyncio
async def test_get_too_many_422(client):
    r = await client.get("/api/v1/broker-links", params={"symbols": ",".join(f"S{i}" for i in range(51))})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_bad_chars_422(client):
    r = await client.get("/api/v1/broker-links", params={"symbols": "AAPL;DROP"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_codes_and_put_require_token(client):
    assert (await client.get("/api/v1/broker-links/codes")).status_code in (401, 403)
    r = await client.put("/api/v1/broker-links/WEN", json={"toss_url": None, "verified": True})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_codes_lists_unverified_first(client):
    r = await client.get("/api/v1/broker-links/codes", headers={"X-API-Token": TOKEN})
    assert r.status_code == 200
    assert [x["symbol"] for x in r.json()["codes"]] == ["WEN", "AAPL"]


@pytest.mark.asyncio
async def test_put_parses_url(client):
    h = {"X-API-Token": TOKEN}
    r = await client.put("/api/v1/broker-links/wen", headers=h,
                         json={"toss_url": "https://www.tossinvest.com/stocks/US19810527002/order", "verified": True})
    assert r.status_code == 200 and r.json()["toss_code"] == "US19810527002"
    link = (await client.get("/api/v1/broker-links", params={"symbols": "WEN"})).json()["links"][0]
    assert link == {"symbol": "WEN", "kind": "order", "url": "https://www.tossinvest.com/stocks/US19810527002/order", "verified": True}


@pytest.mark.asyncio
async def test_put_verify_only_keeps_code(client):
    h = {"X-API-Token": TOKEN}
    r = await client.put("/api/v1/broker-links/WEN", headers=h, json={"toss_url": None, "verified": True})
    assert r.status_code == 200 and r.json()["toss_code"] == "US19810527001" and r.json()["source"] == "manual"


@pytest.mark.asyncio
async def test_put_bad_url_422(client):
    h = {"X-API-Token": TOKEN}
    r = await client.put("/api/v1/broker-links/WEN", headers=h, json={"toss_url": "https://evil.example/US19810527001", "verified": True})
    assert r.status_code == 422
    r = await client.put("/api/v1/broker-links/NEW", headers=h, json={"toss_url": None, "verified": True})
    assert r.status_code == 422  # 코드가 없는 종목을 확인함으로 바꿀 수 없음
