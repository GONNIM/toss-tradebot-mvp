"""Serenity signal → 실 주가 대조 백테스트 · Phase L5 · 2026-08-02.

원본: docs/plans/serenity-integration/02-backend-arch.md §6

파이프라인:
    SerenitySignal (backtest 없음) → yfinance.history(signal_date, +200d)
    → 5·10·30·60·180 일 후 종가 return 계산 → SerenityBacktest upsert

주의:
    - yfinance rate limit 심각 · 배치·재시도·비동기 처리 유의
    - non-US 심볼(SEK·KRX·TW)은 ticker_map.py 매핑
    - weekend·holiday 로 signal_date 종가 없으면 다음 거래일 사용
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import not_, select
from sqlalchemy.exc import IntegrityError

from backend.services.db import get_session
from backend.services.models import SerenityBacktest, SerenitySignal
from backend.services.ticker_map import to_yfinance_symbol

logger = logging.getLogger(__name__)

RETURN_WINDOWS = (5, 10, 30, 60, 180)
_HISTORY_WINDOW_DAYS = 200


def _round_pct(a: float, b: float) -> float:
    if a <= 0:
        return 0.0
    return round((b - a) / a * 100, 2)


def backtest_signal(signal: dict[str, Any], *, ticker_client=None) -> Optional[dict]:
    """개별 signal 백테스트 · yfinance sync 호출.

    signal dict 필요 필드: id · ticker · extracted_at (datetime)
    ticker_client · 테스트 mock 주입 지점 (콜러블 · returns yf.Ticker 유사 객체)

    반환: SerenityBacktest 생성용 dict · yfinance 응답 없으면 None.
    """
    ticker_raw = signal["ticker"]
    yahoo_symbol = to_yfinance_symbol(ticker_raw)
    signal_at = signal["extracted_at"]
    signal_date = (
        signal_at.date() if isinstance(signal_at, datetime) else datetime.fromisoformat(str(signal_at)).date()
    )
    end_date = signal_date + timedelta(days=_HISTORY_WINDOW_DAYS)

    try:
        if ticker_client is None:
            import yfinance as yf  # 지연 import · 테스트에서 mock 대체 가능
            stock = yf.Ticker(yahoo_symbol)
        else:
            stock = ticker_client(yahoo_symbol)
        hist = stock.history(start=signal_date.isoformat(), end=end_date.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[serenity] yfinance history 실패 · %s (%s) · %s",
                       ticker_raw, yahoo_symbol, exc)
        return None

    if hist is None or getattr(hist, "empty", True):
        logger.debug("[serenity] history empty · %s @%s", yahoo_symbol, signal_date)
        return None

    try:
        signal_price = float(hist.iloc[0]["Close"])
    except (KeyError, IndexError, ValueError):
        return None
    if signal_price <= 0:
        return None

    returns: dict[str, Optional[float]] = {f"return_{d}d": None for d in RETURN_WINDOWS}
    for days in RETURN_WINDOWS:
        if len(hist) > days:
            try:
                future_price = float(hist.iloc[days]["Close"])
                returns[f"return_{days}d"] = _round_pct(signal_price, future_price)
            except (KeyError, IndexError, ValueError):
                continue

    return {
        "signal_id": signal["id"],
        "ticker": ticker_raw,
        "signal_date": signal_date.isoformat(),
        "price_at_signal": round(signal_price, 4),
        **returns,
    }


async def load_pending_signals(limit: int = 100) -> list[dict]:
    """SerenityBacktest 미존재 signal 최근순 조회."""
    async with get_session() as session:
        exists_sub = (
            select(SerenityBacktest.signal_id)
            .where(SerenityBacktest.signal_id == SerenitySignal.id)
            .exists()
        )
        stmt = (
            select(SerenitySignal)
            .where(not_(exists_sub))
            .order_by(SerenitySignal.extracted_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "ticker": r.ticker, "extracted_at": r.extracted_at}
        for r in rows
    ]


async def _persist_backtest(payload: dict) -> bool:
    """단일 백테스트 upsert. race 시 update 로 재시도."""
    async with get_session() as session:
        row = SerenityBacktest(
            id=str(uuid.uuid4()),
            signal_id=payload["signal_id"],
            ticker=payload["ticker"],
            signal_date=payload["signal_date"],
            price_at_signal=payload["price_at_signal"],
            return_5d=payload.get("return_5d"),
            return_10d=payload.get("return_10d"),
            return_30d=payload.get("return_30d"),
            return_60d=payload.get("return_60d"),
            return_180d=payload.get("return_180d"),
        )
        session.add(row)
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()

    # 이미 있는 signal_id · update
    async with get_session() as s2:
        target = (await s2.execute(
            select(SerenityBacktest).where(SerenityBacktest.signal_id == payload["signal_id"])
        )).scalar_one()
        target.ticker = payload["ticker"]
        target.signal_date = payload["signal_date"]
        target.price_at_signal = payload["price_at_signal"]
        for w in RETURN_WINDOWS:
            setattr(target, f"return_{w}d", payload.get(f"return_{w}d"))
        target.computed_at = datetime.utcnow()
        await s2.commit()
    return True


async def refresh_backtests(
    batch_size: int = 100,
    *,
    concurrency: int = 4,
    ticker_client=None,
) -> dict:
    """미처리 signals 배치 백테스트.

    반환: {"pending": N, "computed": M, "failed": K}
    """
    pending = await load_pending_signals(limit=batch_size)
    if not pending:
        return {"pending": 0, "computed": 0, "failed": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"pending": len(pending), "computed": 0, "failed": 0}

    async def _one(sig: dict) -> None:
        async with sem:
            payload = await asyncio.to_thread(
                backtest_signal, sig, ticker_client=ticker_client,
            )
            if payload is None:
                stats["failed"] += 1
                return
            if await _persist_backtest(payload):
                stats["computed"] += 1

    await asyncio.gather(*[_one(s) for s in pending])
    return stats
