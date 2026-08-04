"""벤치마크 지수 (IWM · SPY) 종가 캐시 배치 · Phase L14 · 2026-08-04.

목적: 각 first_mention 이벤트마다 동일 signal_date 기준 벤치마크 forward return 계산
→ 초과수익 (signal_return − benchmark_return) 판정.

크론: 매일 00:30 KST · IWM + SPY 400일 종가 upsert.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.services.db import get_session
from backend.services.models import SerenityBenchmarkPrice

logger = logging.getLogger(__name__)

BENCHMARK_SYMBOLS: tuple[str, ...] = ("IWM", "SPY")
_HISTORY_DAYS = 400
_CONCURRENCY = 2  # 지수 2개 병렬 · yfinance rate limit 여유


def _fetch_history(symbol: str, *, ticker_client=None):
    """yfinance history 400d 조회 · (date_str → (open, close)) dict."""
    try:
        if ticker_client is None:
            import yfinance as yf
            stock = yf.Ticker(symbol)
        else:
            stock = ticker_client(symbol)
        today = datetime.utcnow().date()
        hist = stock.history(
            start=(today - timedelta(days=_HISTORY_DAYS)).isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[benchmark] yfinance 실패 · %s · %s", symbol, exc)
        return {}

    if hist is None or getattr(hist, "empty", True):
        return {}

    out: dict[str, tuple[Optional[float], Optional[float]]] = {}
    try:
        for idx, row in hist.iterrows():
            date_str = idx.date().isoformat()
            out[date_str] = (float(row["Open"]), float(row["Close"]))
    except (KeyError, ValueError, AttributeError) as exc:
        logger.warning("[benchmark] parse 실패 · %s · %s", symbol, exc)
        return {}
    return out


async def _upsert_prices(symbol: str, rows: dict[str, tuple[Optional[float], Optional[float]]]) -> int:
    """symbol × dates 배치 upsert · 반환: 신규+갱신 건수."""
    if not rows:
        return 0
    async with get_session() as session:
        # 기존 rows 조회
        existing_rows = (await session.execute(
            select(SerenityBenchmarkPrice)
            .where(SerenityBenchmarkPrice.symbol == symbol)
            .where(SerenityBenchmarkPrice.snapshot_date.in_(list(rows.keys())))
        )).scalars().all()
        existing_map = {r.snapshot_date: r for r in existing_rows}

        touched = 0
        for date_str, (open_val, close_val) in rows.items():
            if date_str in existing_map:
                obj = existing_map[date_str]
                obj.open = open_val
                obj.close = close_val
                obj.fetched_at = datetime.utcnow()
            else:
                session.add(SerenityBenchmarkPrice(
                    symbol=symbol,
                    snapshot_date=date_str,
                    open=open_val,
                    close=close_val,
                ))
            touched += 1
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning("[benchmark] upsert IntegrityError · %s", symbol)
            return 0
    return touched


async def refresh_benchmark_prices(*, ticker_client=None) -> dict:
    """IWM + SPY 400d 종가 배치 upsert.

    반환: {"IWM": N, "SPY": M} · 각 심볼별 upsert 건수.
    """
    sem = asyncio.Semaphore(_CONCURRENCY)
    stats: dict[str, int] = {}

    async def _one(symbol: str) -> None:
        async with sem:
            rows = await asyncio.to_thread(_fetch_history, symbol, ticker_client=ticker_client)
            n = await _upsert_prices(symbol, rows)
            stats[symbol] = n

    await asyncio.gather(*[_one(s) for s in BENCHMARK_SYMBOLS])
    logger.info("[benchmark] refresh 완료 · %s", stats)
    return stats


async def benchmark_forward_return(
    symbol: str,
    signal_date: str,
    days: int,
) -> Optional[float]:
    """벤치마크 forward return · signal_date 종가 대비 +days 거래일 후 종가 (%).

    signal_date 는 YYYY-MM-DD. 거래일 인덱스 계산 위해 signal_date 이상 첫 row + N번째 row 사용.
    데이터 부족·결측 시 None.
    """
    async with get_session() as session:
        rows = list((await session.execute(
            select(SerenityBenchmarkPrice)
            .where(SerenityBenchmarkPrice.symbol == symbol)
            .where(SerenityBenchmarkPrice.snapshot_date >= signal_date)
            .order_by(SerenityBenchmarkPrice.snapshot_date)
            .limit(days + 2)  # signal_date 이상 첫 거래일 + N 개 · 여유 1
        )).scalars().all())

    if len(rows) <= days:
        return None
    base = rows[0].close
    target = rows[days].close
    if base is None or target is None or base <= 0:
        return None
    return round((target - base) / base * 100, 2)
