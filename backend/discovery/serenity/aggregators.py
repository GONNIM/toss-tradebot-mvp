"""Serenity signals → 티커별 aggregate · Phase L4 · 2026-08-02.

Supabase RPC 대체 (SQLAlchemy async 재작성).

원본 계약 (문서 02 §4.4):
    mention_count_90d · bullish_pct_90d · last_signal_at · thesis_types (집합)
    active tickers (최근 N일 signal 있는 티커 목록)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import distinct, func, select

from backend.services.db import get_session
from backend.services.models import SerenitySignal


async def aggregate_signals(ticker: str, *, days: int = 90) -> dict:
    """단일 티커의 최근 N일 signal aggregate.

    반환 필드:
      mention_count_days · bullish_pct_days · last_signal_at · thesis_types (list)
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        rows = list((await session.execute(
            select(SerenitySignal).where(
                SerenitySignal.ticker == ticker,
                SerenitySignal.extracted_at >= cutoff,
            )
        )).scalars().all())

    total = len(rows)
    bullish = sum(1 for r in rows if r.sentiment == "bullish")
    bearish = sum(1 for r in rows if r.sentiment == "bearish")
    neutral = sum(1 for r in rows if r.sentiment == "neutral")
    calibration = sum(1 for r in rows if r.sentiment == "calibration")
    bullish_pct = (100.0 * bullish / total) if total else 0.0
    thesis_types = sorted({r.thesis_type for r in rows if r.thesis_type})
    last_signal_at = max((r.extracted_at for r in rows), default=None)

    return {
        "ticker": ticker,
        "days": days,
        "mention_count": total,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "calibration_count": calibration,
        "bullish_pct": round(bullish_pct, 2),
        "thesis_types": thesis_types,
        "last_signal_at": last_signal_at,
    }


async def active_tickers(*, days: int = 90) -> list[str]:
    """최근 N일 signal 이 하나라도 있는 티커 목록."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        rows = list((await session.execute(
            select(distinct(SerenitySignal.ticker))
            .where(SerenitySignal.extracted_at >= cutoff)
        )).scalars().all())
    return sorted(rows)


async def signals_last_seen() -> Optional[datetime]:
    """전체 signal 최신 extracted_at (모니터링용)."""
    async with get_session() as session:
        result = (await session.execute(
            select(func.max(SerenitySignal.extracted_at))
        )).scalar_one_or_none()
    return result
