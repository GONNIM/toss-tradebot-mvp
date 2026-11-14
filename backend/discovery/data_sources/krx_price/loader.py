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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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


async def _upsert_rows(session: AsyncSession, ticker: str, rows: list[dict]) -> tuple[int, int]:
    """한 종목 일봉을 한 번에 UPSERT. (inserted, updated) 를 돌려준다. commit 은 호출자.

    개수 SELECT 1회(기존 행 수) → INSERT … ON CONFLICT(ticker, date) DO UPDATE.
    값이 같아도 기존 행이면 updated 로 센다 (옛 코드와 같은 뜻). fetched_at 은 옛 코드처럼 갱신하지 않는다.
    """
    keys = [r["date"] for r in rows]
    existing = (
        await session.execute(
            select(func.count())
            .select_from(KrxDailyCandle)
            .where(KrxDailyCandle.ticker == ticker, KrxDailyCandle.date.in_(keys))
        )
    ).scalar_one()
    dialect = session.get_bind().dialect.name  # SQLite(현재) · Postgres(전환 대비) 모두 같은 ON CONFLICT 문법
    stmt = (pg_insert if dialect == "postgresql" else sqlite_insert)(KrxDailyCandle)
    stmt = stmt.on_conflict_do_update(
        index_elements=[KrxDailyCandle.ticker, KrxDailyCandle.date],
        set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "volume", "return_pct")},
    )
    await session.execute(stmt, rows)
    return len(rows) - existing, existing


def _rows_from_df(ticker: str, df: pd.DataFrame) -> list[dict]:
    rows: dict[str, dict] = {}  # 같은 날짜가 두 번 오면 뒤 값이 이긴다 (옛 코드의 덮어쓰기와 같음)
    for d, row in df.iterrows():
        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        rows[date_str] = {
            "ticker": ticker,
            "date": date_str,
            "open": float(row["시가"]),
            "high": float(row["고가"]),
            "low": float(row["저가"]),
            "close": float(row["종가"]),
            "volume": float(row["거래량"]),
            "return_pct": float(row.get("등락률") or 0.0),
        }
    return list(rows.values())


async def ingest_24m_candles(
    session: AsyncSession,
    tickers: Iterable[str],
    end_date: date | None = None,
) -> dict[str, int]:
    """매핑 종목들 × 24개월 일봉 → KrxDailyCandle 적재.

    중복 키(ticker, date) 는 UPSERT (덮어쓰기).

    1102-08: 종목마다 「받기(잠금 밖) → UPSERT → 바로 commit」. 받는 동안 SQLite 쓰기 잠금을 잡지 않는다
    (예전엔 끝까지 commit 이 없어 51종목 받는 내내 다른 잡의 쓰기가 막혔다).
    쓰기 예외는 그 종목만 rollback 하고 failures 에 센다.
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

        try:
            rows = _rows_from_df(ticker, df)
            inserted, updated = await _upsert_rows(session, ticker, rows)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning(f"[krx_candle] {ticker} write fail: {e}")
            stats["failures"] += 1
            continue

        stats["rows_inserted"] += inserted
        stats["rows_updated"] += updated
        logger.info(
            f"[krx_candle] {ticker}: {len(df)} candles ({df.index[0]} ~ {df.index[-1]})"
        )

    return stats
