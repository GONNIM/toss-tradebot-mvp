"""Toss rankings 폴러 · Sprint 1 T39.

10초 주기로 GET /api/v1/rankings 폴링 · KR 거래대금 순위 100 종목 저장.
KOSDAQ 유니버스와 교차 필터 · 각 종목의 rank velocity (rank change per window) 산출.

계획서: docs/plans/sniper/00-sprint1-plan.md §2-2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select

from backend.execution.brokers.toss_client import TossClient, get_toss_client
from backend.services.db import get_session
from backend.services.models import LiveTapeRanking, LiveTapeUniverse

from .params import get_sniper_params

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankingSnapshot:
    """단일 종목 랭킹 스냅샷 · in-memory 순회용."""
    ticker: str
    rank: int
    last_price: Optional[float]
    change_rate: Optional[float]
    trading_amount: Optional[float]
    captured_at: datetime


async def poll_rankings(toss_client: Optional[TossClient] = None) -> dict:
    """단일 폴 · rankings 조회 · 유니버스 교차 · DB 저장.

    Returns:
        {"total_ranked": N, "universe_matched": M, "saved": K, "captured_at": iso}
    """
    client = toss_client or get_toss_client()
    now = datetime.now(tz=timezone.utc)

    # 1) rankings 조회
    env = client.rankings(count=100)
    result = env.result if isinstance(env.result, dict) else {}
    items = result.get("rankings") or []

    # 2) 유니버스 티커 집합 로드
    async with get_session() as session:
        rows = (await session.execute(select(LiveTapeUniverse.ticker))).all()
        universe = {r[0] for r in rows}

    # 3) 교차 필터 후 저장
    saved = 0
    async with get_session() as session:
        for item in items:
            ticker = item.get("symbol")
            if not ticker or ticker not in universe:
                continue
            price = item.get("price") or {}
            entry = LiveTapeRanking(
                ticker=ticker,
                rank=int(item.get("rank")) if item.get("rank") else None,
                volume_amount=float(item.get("tradingAmount", 0) or 0),
                price=float(price.get("lastPrice", 0) or 0) or None,
                return_pct=float(price.get("changeRate", 0) or 0) or None,
                captured_at=now,
            )
            session.add(entry)
            saved += 1

    stats = {
        "total_ranked": len(items),
        "universe_matched": saved,
        "saved": saved,
        "captured_at": now.isoformat(),
    }
    logger.info(
        "rankings poll · %d/100 유니버스 매치 · rankedAt=%s",
        saved, result.get("rankedAt"),
    )
    return stats


async def rank_velocity(ticker: str, window_sec: int = 300) -> Optional[dict]:
    """단일 종목의 rank velocity 산출.

    window_sec 이내 스냅샷들의 첫→최신 rank 변화. 양수면 순위 상승 (rank 감소).

    Returns:
        {"first_rank", "last_rank", "delta", "snapshots"} or None if <2 스냅샷
    """
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=window_sec)
    async with get_session() as session:
        stmt = (
            select(LiveTapeRanking)
            .where(LiveTapeRanking.ticker == ticker)
            .where(LiveTapeRanking.captured_at >= since)
            .order_by(LiveTapeRanking.captured_at.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    if first.rank is None or last.rank is None:
        return None
    delta = first.rank - last.rank  # 양수 = 순위 상승 (rank 값 감소)
    return {
        "ticker": ticker,
        "first_rank": first.rank,
        "last_rank": last.rank,
        "delta": delta,
        "snapshots": len(rows),
        "last_price": last.price,
        "last_return_pct": last.return_pct,
    }


async def top_rank_movers(window_sec: int = 300, min_delta: int = 20) -> list[dict]:
    """window 내 rank velocity 상위 종목 (delta ≥ min_delta).

    급등 candidate 감지의 핵심.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=window_sec)
    async with get_session() as session:
        stmt = (
            select(LiveTapeRanking.ticker)
            .where(LiveTapeRanking.captured_at >= since)
            .distinct()
        )
        tickers = [r[0] for r in (await session.execute(stmt)).all()]

    movers: list[dict] = []
    for t in tickers:
        v = await rank_velocity(t, window_sec=window_sec)
        if v and v["delta"] >= min_delta:
            movers.append(v)
    movers.sort(key=lambda x: -x["delta"])
    return movers


async def cleanup_old_snapshots(keep_hours: int = 6) -> int:
    """오래된 스냅샷 정리 · 오늘 세션만 유지 (하루 최대 3600 * 6 = 21,600건 상한 근사)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=keep_hours)
    async with get_session() as session:
        stmt = delete(LiveTapeRanking).where(LiveTapeRanking.captured_at < cutoff)
        result = await session.execute(stmt)
    return int(result.rowcount or 0)
