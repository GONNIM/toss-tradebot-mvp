"""Crazy universe 시총·가격 필터 (1027-03 · 사용자 B 승인)."""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select, text

from backend.scheduler import cron
from backend.services.db import engine, ensure_columns, get_session, init_db
from backend.services.models import TickerUniverse


def _row(symbol: str, mcap, price) -> TickerUniverse:
    return TickerUniverse(symbol=symbol, market="NASDAQ", category="dry_run",
                          company_name=symbol, market_cap=mcap, current_price=price)


@pytest.mark.asyncio
async def test_crazy_needs_mcap_and_price(monkeypatch):
    """DB 행 없음 · 시총 None · 시총 미만 · 가격 None · 가격 미만 → Crazy 제외 · 둘 다 넘으면 포함 · Moonshot 은 전부."""
    await init_db()
    async with get_session() as session:
        await session.execute(delete(TickerUniverse))
        session.add_all([
            _row("BIG", 2e9, 50.0),
            _row("NOMC", None, 50.0),
            _row("SMALL", 5e6, 2.0),
            _row("NOPX", 2e9, None),
            _row("PENNY", 2e9, 0.5),
        ])
    monkeypatch.setattr(cron, "WATCHLIST", ["BIG", "NOMC", "SMALL", "NOPX", "PENNY", "NOROW"])

    universe = await cron._load_dry_run_universe()

    assert {i.ticker for i in universe if i.is_crazy} == {"BIG"}
    assert all(i.is_moonshot for i in universe)
    assert len(universe) == 6


@pytest.mark.asyncio
async def test_current_price_column_added_to_old_table():
    """옛 표에 current_price 가 없으면 ensure_columns 가 넣는다 (서버 DB 마이그레이션 경로)."""
    await init_db()
    async with engine.begin() as conn:
        await conn.run_sync(TickerUniverse.__table__.drop)
        await conn.execute(text(
            "CREATE TABLE ticker_universe (symbol VARCHAR(10) PRIMARY KEY, market VARCHAR(20), "
            "category VARCHAR(30), sector VARCHAR(50), company_name VARCHAR(200), market_cap FLOAT, "
            "active BOOLEAN, notes TEXT, created_at DATETIME, updated_at DATETIME)"
        ))
    await ensure_columns()
    async with engine.begin() as conn:
        cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(ticker_universe)"))).all()}
    assert "current_price" in cols
    async with get_session() as session:
        assert (await session.execute(select(TickerUniverse))).scalars().all() == []
