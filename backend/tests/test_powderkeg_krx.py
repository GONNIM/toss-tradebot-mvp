"""P7-1c KRX 수집기 단위 테스트 · FinanceDataReader 모킹."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.collectors import krx_market as km
from backend.powderkeg.collectors.krx_market import (
    collect_market_snapshot,
    latest_market,
)
from backend.services.db import get_session, init_db
from backend.services.models import KrxMarketSnapshot


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(KrxMarketSnapshot))
    yield


def _mock_listing_df(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def _patch_fdr(monkeypatch, kospi_rows, kosdaq_rows, adv60_series=None):
    import sys
    stub = MagicMock()

    def _stock_listing(market):
        if market == "KOSPI":
            return _mock_listing_df(kospi_rows)
        return _mock_listing_df(kosdaq_rows)

    stub.StockListing = _stock_listing

    if adv60_series is not None:
        import pandas as pd
        def _data_reader(ticker, start, end):
            data = adv60_series.get(ticker)
            if data is None:
                return pd.DataFrame()
            # DataFrame with Close/Volume/Amount columns
            return pd.DataFrame(data)
        stub.DataReader = _data_reader

    monkeypatch.setitem(sys.modules, "FinanceDataReader", stub)


@pytest.mark.asyncio
async def test_collect_upserts_kospi_and_kosdaq(monkeypatch):
    kospi_rows = [
        {"Code": "005930", "Name": "삼성전자", "Close": 72700, "Marcap": 430_000_000_000_000, "PBR": 0.45},
        {"Code": "000660", "Name": "SK하이닉스", "Close": 195000, "Marcap": 141_000_000_000_000, "PBR": 1.20},
    ]
    kosdaq_rows = [
        {"Code": "042700", "Name": "한미반도체", "Close": 55000, "Marcap": 5_000_000_000_000, "PBR": 3.5},
    ]
    _patch_fdr(monkeypatch, kospi_rows, kosdaq_rows)

    stats = await collect_market_snapshot(snapshot_date="2026-07-15")
    assert stats["total"] == 3
    assert stats["upserted"] == 3

    async with get_session() as session:
        rows = (await session.execute(select(KrxMarketSnapshot))).scalars().all()
    tickers = {r.ticker for r in rows}
    assert tickers == {"005930", "000660", "042700"}
    samsung = next(r for r in rows if r.ticker == "005930")
    assert samsung.market == "KOSPI"
    assert samsung.name == "삼성전자"
    assert samsung.close_price == 72700
    assert samsung.pbr == 0.45


@pytest.mark.asyncio
async def test_collect_filters_by_tickers(monkeypatch):
    kospi_rows = [
        {"Code": "005930", "Close": 72700, "Marcap": 430e12, "PBR": 0.45},
        {"Code": "000660", "Close": 195000, "Marcap": 141e12, "PBR": 1.20},
    ]
    _patch_fdr(monkeypatch, kospi_rows, [])

    stats = await collect_market_snapshot(
        tickers={"005930"}, snapshot_date="2026-07-15",
    )
    assert stats["total"] == 1
    async with get_session() as session:
        rows = (await session.execute(select(KrxMarketSnapshot))).scalars().all()
    assert len(rows) == 1 and rows[0].ticker == "005930"


@pytest.mark.asyncio
async def test_collect_reupsert_same_date(monkeypatch):
    """같은 snapshot_date 로 두 번 호출 · 두 번째 값으로 upsert."""
    _patch_fdr(monkeypatch,
               [{"Code": "005930", "Close": 100, "Marcap": 1e12, "PBR": 0.5}],
               [])
    await collect_market_snapshot(snapshot_date="2026-07-15")

    _patch_fdr(monkeypatch,
               [{"Code": "005930", "Close": 110, "Marcap": 1.1e12, "PBR": 0.55}],
               [])
    await collect_market_snapshot(snapshot_date="2026-07-15")

    async with get_session() as session:
        rows = (await session.execute(select(KrxMarketSnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].close_price == 110   # 최신 값


@pytest.mark.asyncio
async def test_collect_with_adv60(monkeypatch):
    kospi_rows = [{"Code": "005930", "Close": 100, "Marcap": 1e12, "PBR": 0.5}]
    adv60 = {
        "005930": {
            "Close": [100] * 60,
            "Volume": [10_000] * 60,
            "Amount": [1_000_000] * 60,   # 100만 원 평균 (테스트용)
        },
    }
    _patch_fdr(monkeypatch, kospi_rows, [], adv60_series=adv60)

    stats = await collect_market_snapshot(
        snapshot_date="2026-07-15", include_adv60=True,
    )
    assert stats["adv60_computed"] == 1
    async with get_session() as session:
        row = (await session.execute(select(KrxMarketSnapshot))).scalar_one()
    assert row.avg_daily_amount_60d == 1_000_000


@pytest.mark.asyncio
async def test_latest_market_returns_most_recent(monkeypatch):
    _patch_fdr(monkeypatch,
               [{"Code": "005930", "Close": 100, "Marcap": 1e12, "PBR": 0.5}], [])
    await collect_market_snapshot(snapshot_date="2026-07-13")
    await collect_market_snapshot(snapshot_date="2026-07-15")

    r = await latest_market("005930")
    assert r is not None
    assert r.snapshot_date == "2026-07-15"


@pytest.mark.asyncio
async def test_nan_pbr_handled(monkeypatch):
    """PBR NaN · None 저장."""
    kospi_rows = [{"Code": "005930", "Close": 100, "Marcap": 1e12, "PBR": float("nan")}]
    _patch_fdr(monkeypatch, kospi_rows, [])
    await collect_market_snapshot(snapshot_date="2026-07-15")
    async with get_session() as session:
        row = (await session.execute(select(KrxMarketSnapshot))).scalar_one()
    assert row.pbr is None
