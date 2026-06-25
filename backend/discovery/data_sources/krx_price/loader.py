"""KRX 종목 메타·일봉 수집 → SQLite 적재 (B-2c).

- fetch_all_meta: FDR StockListing 으로 KRX 전 종목 메타 1회 fetch.
- upsert_meta: 매핑 종목 메타 → KrxStockMeta 테이블.
- fetch_daily_candles: pykrx 로 단일 종목 24M 일봉.
- ingest_24m_candles: 매핑 51 종목 × 24M 일봉 → KrxDailyCandle 테이블.

pykrx 는 동기 라이브러리 → asyncio.to_thread 로 비차단.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Iterable

import FinanceDataReader as fdr
import pandas as pd
from pykrx import stock as pykrx_stock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.models import KrxDailyCandle, KrxStockMeta

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 종목 메타 (FDR)
# ─────────────────────────────────────────────────────────────────


async def fetch_all_meta() -> pd.DataFrame:
    """FDR StockListing('KRX') → KRX 전 종목 메타 DataFrame.

    컬럼: Code, Name, Market, Close, Marcap, Stocks, ...
    """
    return await asyncio.to_thread(fdr.StockListing, "KRX")


async def upsert_meta(
    session: AsyncSession,
    tickers: Iterable[str],
) -> dict[str, int]:
    """매핑 종목들의 메타를 FDR 에서 fetch → KrxStockMeta 갱신."""
    krx_df = await fetch_all_meta()
    by_code = {row["Code"]: row for _, row in krx_df.iterrows()}

    stats = {"updated": 0, "inserted": 0, "missing": 0}
    for code in tickers:
        row = by_code.get(code)
        if row is None:
            stats["missing"] += 1
            logger.warning(f"[krx_meta] {code} not in FDR StockListing")
            continue

        existing = (
            await session.execute(
                select(KrxStockMeta).where(KrxStockMeta.ticker == code)
            )
        ).scalar_one_or_none()

        marcap = float(row.get("Marcap") or 0) or None
        shares = float(row.get("Stocks") or 0) or None
        last_close = float(row.get("Close") or 0) or None
        market = row.get("Market")

        if existing is None:
            session.add(
                KrxStockMeta(
                    ticker=code,
                    name=row["Name"],
                    market=market,
                    market_cap_krw=marcap,
                    shares_outstanding=shares,
                    last_close=last_close,
                )
            )
            stats["inserted"] += 1
        else:
            existing.name = row["Name"]
            existing.market = market
            existing.market_cap_krw = marcap
            existing.shares_outstanding = shares
            existing.last_close = last_close
            stats["updated"] += 1

    return stats


# ─────────────────────────────────────────────────────────────────
# 일봉 (pykrx)
# ─────────────────────────────────────────────────────────────────


def _fetch_ohlcv_sync(start: str, end: str, ticker: str) -> pd.DataFrame:
    return pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)


async def fetch_daily_candles(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """단일 종목 일봉. pykrx 호출은 to_thread 로 비차단."""
    return await asyncio.to_thread(
        _fetch_ohlcv_sync,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        ticker,
    )


async def ingest_24m_candles(
    session: AsyncSession,
    tickers: Iterable[str],
    end_date: date | None = None,
) -> dict[str, int]:
    """매핑 종목들 × 24개월 일봉 → KrxDailyCandle 적재.

    중복 키(ticker, date) 는 UPSERT (덮어쓰기).
    """
    end = end_date or date.today()
    start = end - timedelta(days=24 * 31)  # 약 24개월

    stats = {"tickers": 0, "rows_inserted": 0, "rows_updated": 0, "failures": 0}
    tickers_set = sorted(set(tickers))

    for ticker in tickers_set:
        stats["tickers"] += 1
        try:
            df = await fetch_daily_candles(ticker, start, end)
        except Exception as e:
            logger.warning(f"[krx_candle] {ticker} fetch fail: {e}")
            stats["failures"] += 1
            continue

        if df.empty:
            logger.warning(f"[krx_candle] {ticker} empty df")
            continue

        for d, row in df.iterrows():
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            existing = (
                await session.execute(
                    select(KrxDailyCandle).where(
                        KrxDailyCandle.ticker == ticker,
                        KrxDailyCandle.date == date_str,
                    )
                )
            ).scalar_one_or_none()

            ret_pct = float(row.get("등락률") or 0.0)
            close = float(row["종가"])
            open_ = float(row["시가"])
            high = float(row["고가"])
            low = float(row["저가"])
            volume = float(row["거래량"])

            if existing is None:
                session.add(
                    KrxDailyCandle(
                        ticker=ticker,
                        date=date_str,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                        return_pct=ret_pct,
                    )
                )
                stats["rows_inserted"] += 1
            else:
                existing.open = open_
                existing.high = high
                existing.low = low
                existing.close = close
                existing.volume = volume
                existing.return_pct = ret_pct
                stats["rows_updated"] += 1

        # 메모리/세션 부담 줄이기 위해 종목 별 flush
        await session.flush()
        logger.info(
            f"[krx_candle] {ticker}: {len(df)} candles ({df.index[0]} ~ {df.index[-1]})"
        )

    return stats
