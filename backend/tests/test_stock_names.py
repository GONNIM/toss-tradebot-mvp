"""종목명 읽기 조회 (1023-05 Task 3)."""
from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.services import stock_names as sn


@pytest_asyncio.fixture
async def db():
    from backend.services.db import get_session, init_db
    from backend.services.models import KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList

    await init_db()
    async with get_session() as session:
        for model in (KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList):
            await session.execute(delete(model))
    yield


async def _add(*rows):
    from backend.services.db import get_session

    async with get_session() as session:
        for r in rows:
            session.add(r)


@pytest.mark.asyncio
async def test_lookup_order(db):
    from backend.services.db import get_session
    from backend.services.models import KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList

    await _add(
        KrxMarketSnapshot(ticker="012345", snapshot_date="2026-08-01", name="옛이름"),
        KrxMarketSnapshot(ticker="012345", snapshot_date="2026-08-13", name="스냅샷이름"),
        LiveTapeUniverse(ticker="012345", name="유니버스이름"),
        PowderKegList(run_id="20260813-000000", ticker="012345", name="목록이름", status="passed"),
        KrxStockMeta(ticker="012345", name="메타이름"),
    )
    assert await sn.lookup_kr_name("012345") == "스냅샷이름"
    async with get_session() as session:
        await session.execute(delete(KrxMarketSnapshot))
    assert await sn.lookup_kr_name("012345") == "유니버스이름"
    async with get_session() as session:
        await session.execute(delete(LiveTapeUniverse))
    assert await sn.lookup_kr_name("012345") == "목록이름"
    async with get_session() as session:
        await session.execute(delete(PowderKegList))
    assert await sn.lookup_kr_name("012345") == "메타이름"


@pytest.mark.asyncio
async def test_lookup_missing_returns_none(db):
    assert await sn.lookup_kr_name("999999") is None


@pytest.mark.asyncio
async def test_lookup_error_returns_fallback(db, monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(sn, "_session", _boom)
    assert await sn.lookup_kr_name("012345") is None


@pytest.mark.asyncio
async def test_lookup_timeout(db, monkeypatch):
    async def _slow(ticker):
        await asyncio.sleep(3)
        return "늦은이름"

    monkeypatch.setattr(sn, "_query", _slow)
    t0 = time.monotonic()
    assert await sn.lookup_kr_name("012345") is None
    assert time.monotonic() - t0 < 2.8


@pytest.mark.asyncio
async def test_lookup_cache(db, monkeypatch):
    calls = []

    async def _q(ticker):
        calls.append(ticker)
        return None

    monkeypatch.setattr(sn, "_query", _q)
    cache: dict = {}
    assert await sn.lookup_kr_name("012345", cache) is None
    assert await sn.lookup_kr_name("012345", cache) is None
    assert calls == ["012345"]
