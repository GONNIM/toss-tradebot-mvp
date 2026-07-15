"""Watchlist API 라우트 · Sprint 2 Week 2 T62·T63 통합 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["SNIPER_API_TOKEN"] = "test_token_32chars_00000000000000"

from backend.api.main import app
from backend.discovery.watchlist.store import upsert_signal
from backend.services.db import get_session, init_db
from backend.services.models import LiveTapeUniverse, Watchlist, WatchlistSignal


TRADE_DATE = "2026-07-14"
TOKEN = "test_token_32chars_00000000000000"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
        await session.execute(delete(Watchlist))
        await session.execute(delete(LiveTapeUniverse))
    yield


async def _seed_universe():
    async with get_session() as session:
        for code, name in [("005930", "삼성전자"), ("373220", "LG에너지솔루션")]:
            session.add(LiveTapeUniverse(
                ticker=code, name=name, market="KOSDAQ",
                dept=None, close_price=1000.0, market_cap_krw=100_000_000_000,
                shares=1_000_000, amount_today=1_000_000_000,
                amount_20d_avg=None, is_squeeze_candidate=False,
                refreshed_at=datetime.now(tz=timezone.utc),
            ))


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_watchlist_empty(client):
    resp = await client.get("/api/v1/watchlist", params={"trade_date": TRADE_DATE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == TRADE_DATE
    assert body["size"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_finalize_and_get(client):
    await _seed_universe()
    for _ in range(5):
        await upsert_signal(
            ticker="005930", source="news_yhap", signal_type="headline",
            intensity=1.0, trade_date=TRADE_DATE,
        )
    resp = await client.post(
        "/api/v1/watchlist/finalize",
        headers={"X-API-Token": TOKEN},
        json={"trade_date": TRADE_DATE, "top_n": 5},
    )
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["written"] >= 1

    resp = await client.get("/api/v1/watchlist", params={"trade_date": TRADE_DATE})
    body = resp.json()
    assert body["size"] >= 1
    assert body["items"][0]["ticker"] == "005930"
    assert body["items"][0]["name"] == "삼성전자"


@pytest.mark.asyncio
async def test_manual_add_lock_delete(client):
    await _seed_universe()

    # 수동 add
    resp = await client.post(
        "/api/v1/watchlist/manual",
        headers={"X-API-Token": TOKEN},
        json={"ticker": "373220", "trade_date": TRADE_DATE},
    )
    assert resp.status_code == 200
    item_id = resp.json()["id"]
    assert resp.json()["locked"] is True

    # 조회
    resp = await client.get("/api/v1/watchlist", params={"trade_date": TRADE_DATE})
    items = resp.json()["items"]
    assert any(i["ticker"] == "373220" and i["locked"] for i in items)

    # unlock
    resp = await client.patch(
        f"/api/v1/watchlist/{item_id}/lock",
        headers={"X-API-Token": TOKEN},
        json={"locked": False},
    )
    assert resp.status_code == 200
    assert resp.json()["locked"] is False

    # delete
    resp = await client.delete(
        f"/api/v1/watchlist/{item_id}",
        headers={"X-API-Token": TOKEN},
    )
    assert resp.status_code == 200

    resp = await client.get("/api/v1/watchlist", params={"trade_date": TRADE_DATE})
    assert resp.json()["size"] == 0


@pytest.mark.asyncio
async def test_finalize_requires_token(client):
    resp = await client.post(
        "/api/v1/watchlist/finalize",
        json={"trade_date": TRADE_DATE, "top_n": 5},
    )
    # X-API-Token 없이 → 401/403
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_dates(client):
    await _seed_universe()
    async with get_session() as session:
        session.add(Watchlist(
            trade_date=TRADE_DATE, ticker="005930", name="삼성전자",
            rank=1, composite_score=1.5,
            news_score=0, board_score=0, youtube_score=0,
            event_score=0, prev_day_score=0,
            source_breakdown=None, locked=False, added_by="auto",
        ))
    resp = await client.get("/api/v1/watchlist/dates")
    assert resp.status_code == 200
    assert TRADE_DATE in resp.json()
