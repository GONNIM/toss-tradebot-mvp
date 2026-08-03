"""Serenity 언급 티커 종가 스냅샷 · vs prior close 배치 · Phase L9 · 2026-08-03.

목적: Ticker Card 상단 "vs prior close · +X.X%" 표시.

파이프라인:
    active_tickers(days=180) → yfinance 5d ohlc → 최근 2 종가 → upsert SerenityTickerPrice

특징:
    - to_yfinance_symbol 로 심볼 매핑 (SIVE→SIVE.ST · .KQ→.KS)
    - concurrency 제한 (yfinance rate limit · 배치 4)
    - 실패 티커는 error 필드에 기록 · 재실행 시 재시도

Cron: 매일 09:30 KST (Powderkeg 22:30 이후 오전 · Serenity scorer 08:00 이후)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.discovery.serenity.aggregators import active_tickers
from backend.services.db import get_session
from backend.services.models import DiscoverySerenityScore, SerenityTickerPrice
from backend.services.ticker_map import is_private_or_brand, to_yfinance_symbol

logger = logging.getLogger(__name__)

CONCURRENCY = 4
_HISTORY_DAYS = 7


def _fetch_close_pair(yahoo_symbol: str, *, ticker_client=None) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """(close · prior_close · snapshot_date) 반환 · 실패 시 (None,None,None)."""
    try:
        if ticker_client is None:
            import yfinance as yf
            stock = yf.Ticker(yahoo_symbol)
        else:
            stock = ticker_client(yahoo_symbol)
        today = datetime.utcnow().date()
        hist = stock.history(
            start=(today - timedelta(days=_HISTORY_DAYS)).isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[serenity_price] yfinance 실패 · %s · %s", yahoo_symbol, exc)
        return (None, None, str(exc)[:180])

    if hist is None or getattr(hist, "empty", True) or len(hist) < 2:
        return (None, None, "history 부족")
    try:
        close = float(hist.iloc[-1]["Close"])
        prior = float(hist.iloc[-2]["Close"])
        snapshot_date = hist.index[-1].date().isoformat()
    except (KeyError, IndexError, ValueError) as exc:
        return (None, None, f"parse: {exc}")
    return (close, prior, snapshot_date)


async def _load_all_tickers(days: int = 180) -> list[str]:
    """언급 티커 (signals) + seed 티커 union."""
    async with get_session() as session:
        seed_rows = (await session.execute(select(DiscoverySerenityScore.ticker))).scalars().all()
    seed_set = set(seed_rows)
    signal_set = set(await active_tickers(days=days))
    return sorted(seed_set | signal_set)


async def _upsert_price(ticker: str, yahoo_symbol: str, close, prior, snapshot_date, error: Optional[str]) -> None:
    pct = None
    if close is not None and prior is not None and prior > 0:
        pct = round((close - prior) / prior * 100, 2)
    async with get_session() as session:
        existing = (await session.execute(
            select(SerenityTickerPrice).where(SerenityTickerPrice.ticker == ticker)
        )).scalar_one_or_none()
        if existing:
            existing.snapshot_date = snapshot_date or existing.snapshot_date
            existing.close = close
            existing.prior_close = prior
            existing.vs_prior_close_pct = pct
            existing.yahoo_symbol = yahoo_symbol
            existing.error = error
            existing.fetched_at = datetime.utcnow()
            await session.commit()
            return
        row = SerenityTickerPrice(
            ticker=ticker,
            snapshot_date=snapshot_date or datetime.utcnow().date().isoformat(),
            close=close,
            prior_close=prior,
            vs_prior_close_pct=pct,
            yahoo_symbol=yahoo_symbol,
            error=error,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()


async def refresh_prices(
    *,
    days: int = 180,
    limit: Optional[int] = None,
    ticker_client=None,
) -> dict:
    """언급 티커 전체 종가 스냅샷 upsert.

    반환: {"targets": N, "ok": M, "failed": K}
    """
    tickers = await _load_all_tickers(days=days)
    if limit:
        tickers = tickers[:limit]
    if not tickers:
        return {"targets": 0, "ok": 0, "failed": 0}

    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"targets": len(tickers), "ok": 0, "failed": 0, "skipped": 0}

    async def _one(tk: str) -> None:
        async with sem:
            # Private / 브랜드명 · yfinance 호출 스킵 (rate limit 소모 방지)
            if is_private_or_brand(tk):
                await _upsert_price(tk, tk, None, None, None, "private/브랜드")
                stats["skipped"] = stats.get("skipped", 0) + 1
                return

            symbol = to_yfinance_symbol(tk)
            close, prior, snap_or_err = await asyncio.to_thread(
                _fetch_close_pair, symbol, ticker_client=ticker_client
            )
            # _fetch_close_pair 는 성공 시 3번째가 snapshot_date · 실패 시 error 문자열
            if close is None:
                error = snap_or_err
                snapshot_date = None
                stats["failed"] += 1
            else:
                error = None
                snapshot_date = snap_or_err
                stats["ok"] += 1
            await _upsert_price(tk, symbol, close, prior, snapshot_date, error)

    await asyncio.gather(*[_one(t) for t in tickers])
    return stats
