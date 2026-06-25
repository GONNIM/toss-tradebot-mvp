"""US universe 일봉 snapshot 생성 — 매일 06:00 KST (미국 장 마감 후).

각 ticker 별로 60일 일봉 fetch → RSI / volume z-score / 1D 수익률 계산 →
MemeVolumeSnapshot 적재. Phase 1c 의 confluence 점수가 이 값을 사용.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from backend.discovery.meme_watch.oversold import (
    compute_return_1d,
    compute_rsi,
    compute_volume_z,
)
from backend.discovery.meme_watch.quote_client import fetch_us_daily
from backend.services.db import get_session
from backend.services.models import MemeUniverse, MemeVolumeSnapshot

logger = logging.getLogger(__name__)


async def build_us_snapshots() -> dict:
    """US universe 일봉 snapshot 생성 (Russell 2000 ~2,000 종목)."""
    stats = {"fetched": 0, "saved": 0, "errors": 0, "skipped_short_history": 0}

    # 1) 활성 US 종목 list
    async with get_session() as session:
        active = (
            await session.execute(
                select(MemeUniverse.ticker).where(
                    MemeUniverse.market == "US",
                    MemeUniverse.is_active == True,  # noqa: E712
                )
            )
        ).scalars().all()
    tickers = [t for t in active if t]
    logger.info(f"[meme_volume] US active universe: {len(tickers)}")
    if not tickers:
        return stats

    # 2) yfinance bulk 60일 일봉
    daily = await fetch_us_daily(tickers, period_days=60)
    stats["fetched"] = len(daily)

    # 3) 계산 + 적재
    now = datetime.now()
    async with get_session() as session:
        for ticker, df in daily.items():
            try:
                if df is None or df.empty:
                    continue
                closes = df["Close"]
                volumes = df["Volume"]
                r1d = compute_return_1d(closes)
                if r1d is None:
                    stats["skipped_short_history"] += 1
                    continue
                rsi = compute_rsi(closes)
                vz = compute_volume_z(volumes)
                session.add(
                    MemeVolumeSnapshot(
                        ticker=ticker,
                        snapshot_at=now,
                        volume=float(volumes.iloc[-1]),
                        volume_z_20d=float(vz or 0.0),
                        return_1d_pct=float(r1d),
                        rsi_14=rsi,
                        halt_triggered=False,
                    )
                )
                stats["saved"] += 1
            except Exception as e:
                logger.warning(f"[meme_volume] {ticker} snapshot failed: {e}")
                stats["errors"] += 1
        await session.commit()

    logger.info(f"[meme_volume] done stats={stats}")
    return stats
