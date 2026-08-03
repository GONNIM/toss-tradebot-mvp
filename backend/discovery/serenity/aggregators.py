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
      mention_count · bullish/bearish/neutral/calibration_count · bullish_pct
      thesis_types · last_signal_at
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


async def aggregate_ticker_full(ticker: str) -> dict:
    """이미지 카드 UX 전용 · rolling window + first_mention + stance today.

    반환:
      mentions_today · mentions_7d · mentions_28d · mentions_90d
      stance_today: {bull, bear, neu, cal}
      first_mention_at · last_signal_at
      overall_stance: bullish | bearish | neutral | mixed  (90일 다수결)
      overall_bullish_pct: 90일 bullish %
      thesis_types (90일)
    """
    now = datetime.utcnow()
    d1 = now - timedelta(days=1)
    d7 = now - timedelta(days=7)
    d28 = now - timedelta(days=28)
    d90 = now - timedelta(days=90)

    async with get_session() as session:
        # 90d 창 안 데이터 · 파이썬에서 window filter (호출 1회 · 티커 대량 시 유리)
        rows = list((await session.execute(
            select(SerenitySignal).where(
                SerenitySignal.ticker == ticker,
                SerenitySignal.extracted_at >= d90,
            )
        )).scalars().all())
        # first_mention 은 전체 히스토리 · 별도 min 쿼리
        first_at = (await session.execute(
            select(func.min(SerenitySignal.extracted_at))
            .where(SerenitySignal.ticker == ticker)
        )).scalar_one_or_none()

    def _count(subset, sentiment):
        return sum(1 for r in subset if r.sentiment == sentiment)

    today_rows = [r for r in rows if r.extracted_at >= d1]
    d7_rows = [r for r in rows if r.extracted_at >= d7]
    d28_rows = [r for r in rows if r.extracted_at >= d28]

    stance_today = {
        "bull": _count(today_rows, "bullish"),
        "bear": _count(today_rows, "bearish"),
        "neu": _count(today_rows, "neutral"),
        "cal": _count(today_rows, "calibration"),
    }
    bullish_90d = _count(rows, "bullish")
    bearish_90d = _count(rows, "bearish")
    total_90d = len(rows)
    bullish_pct = (100.0 * bullish_90d / total_90d) if total_90d else 0.0

    # overall stance · 다수결 · 60%+ 우세 시 방향 · 그 외 mixed/neutral
    if total_90d == 0:
        overall = "neutral"
    elif bullish_pct >= 60:
        overall = "bullish"
    elif (100.0 * bearish_90d / total_90d) >= 40:
        overall = "bearish"
    elif bullish_pct < 40 and bullish_pct > 20:
        overall = "mixed"
    else:
        overall = "neutral"

    last_at = max((r.extracted_at for r in rows), default=None)
    thesis_types = sorted({r.thesis_type for r in rows if r.thesis_type})

    return {
        "ticker": ticker,
        "mentions_today": len(today_rows),
        "mentions_7d": len(d7_rows),
        "mentions_28d": len(d28_rows),
        "mentions_90d": total_90d,
        "stance_today": stance_today,
        "first_mention_at": first_at,
        "last_signal_at": last_at,
        "overall_stance": overall,
        "overall_bullish_pct": round(bullish_pct, 2),
        "thesis_types": thesis_types,
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
