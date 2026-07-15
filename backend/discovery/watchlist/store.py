"""Watchlist Signal 저장 계층 · Sprint 2 T58.

야간 축적 signal 을 `watchlist_signal` 테이블로 write. 다음날 Watchlist 승격 판정에서 read.

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T58
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select

from backend.services.db import get_session
from backend.services.models import WatchlistSignal

logger = logging.getLogger(__name__)


# ─── trade_date 유틸 ────────────────────────────────────
_KST = timezone(timedelta(hours=9))


def next_trade_date(now: Optional[datetime] = None) -> str:
    """detected_at 기준 다음 거래일 YYYY-MM-DD (KST).

    간단화 v1 · 15:30 KST 이후 감지 = 다음 영업일 · 그 외 = 당일.
    주말·공휴일 정밀 판정은 Week 2 finalize 잡에서 재보정.
    """
    now = now or datetime.now(tz=timezone.utc)
    kst = now.astimezone(_KST)
    # 마감 (15:30 KST) 이후 감지 → 다음 영업일
    market_close = kst.replace(hour=15, minute=30, second=0, microsecond=0)
    target = kst.date()
    if kst >= market_close:
        target = (kst + timedelta(days=1)).date()
    # 주말 skip
    while target.weekday() >= 5:  # 5=Sat 6=Sun
        target = target + timedelta(days=1)
    return target.isoformat()


# ─── upsert · 중복 방지 ────────────────────────────────
_DEDUP_WINDOW_SEC = 300  # 5m


async def upsert_signal(
    ticker: str,
    source: str,
    signal_type: str,
    intensity: float,
    payload: Optional[dict[str, Any]] = None,
    trade_date: Optional[str] = None,
    detected_at: Optional[datetime] = None,
) -> Optional[int]:
    """단일 signal 저장 · 최근 5분 내 동일 (ticker, source, signal_type) 있으면 skip.

    Returns: 삽입된 row id · 중복이면 None.
    """
    trade_date = trade_date or next_trade_date(detected_at)
    detected_at = detected_at or datetime.now(tz=timezone.utc)
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None

    async with get_session() as session:
        dedup_since = detected_at - timedelta(seconds=_DEDUP_WINDOW_SEC)
        exists_stmt = select(WatchlistSignal.id).where(
            and_(
                WatchlistSignal.ticker == ticker,
                WatchlistSignal.source == source,
                WatchlistSignal.signal_type == signal_type,
                WatchlistSignal.detected_at >= dedup_since,
            )
        ).limit(1)
        exists = (await session.execute(exists_stmt)).scalar_one_or_none()
        if exists is not None:
            return None

        row = WatchlistSignal(
            ticker=ticker,
            source=source,
            signal_type=signal_type,
            intensity=intensity,
            payload_json=payload_json,
            detected_at=detected_at,
            trade_date=trade_date,
        )
        session.add(row)
        await session.flush()
        row_id = row.id
    return row_id


# ─── 조회 ──────────────────────────────────────────────
async def signals_for_date(trade_date: str) -> list[dict[str, Any]]:
    """지정 거래일의 모든 signal · Watchlist 승격 잡용."""
    async with get_session() as session:
        stmt = (
            select(WatchlistSignal)
            .where(WatchlistSignal.trade_date == trade_date)
            .order_by(WatchlistSignal.detected_at.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


async def recent_signals(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
    """최근 N시간 signal · UI/디버그용."""
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    async with get_session() as session:
        stmt = (
            select(WatchlistSignal)
            .where(WatchlistSignal.detected_at >= since)
            .order_by(WatchlistSignal.detected_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


def _serialize(r: WatchlistSignal) -> dict[str, Any]:
    return {
        "id": r.id,
        "ticker": r.ticker,
        "source": r.source,
        "signal_type": r.signal_type,
        "intensity": r.intensity,
        "payload": json.loads(r.payload_json) if r.payload_json else None,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        "trade_date": r.trade_date,
    }
