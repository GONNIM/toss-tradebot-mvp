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


_RANKING_TYPES = (
    "MARKET_TRADING_AMOUNT",   # KR 거래대금 상위 (KOSPI 대형주 편중)
    "TOP_GAINERS",             # KR 등락률 상위 (급등주 · KOSDAQ 진앙지 정합)
    "MARKET_TRADING_VOLUME",   # KR 거래량 상위 (저가주·회전율 활발)
)


async def poll_rankings(toss_client: Optional[TossClient] = None) -> dict:
    """단일 폴 · 3개 rankings 타입 조회 · 유니버스 교차 · DB 저장.

    급등주 정체성 정합:
    - MARKET_TRADING_AMOUNT 만으로는 KOSDAQ 중견주 매치 낮음 (KOSPI 대형주 편중)
    - TOP_GAINERS 추가: 급등 초기 KOSDAQ 종목 즉시 포착
    - MARKET_TRADING_VOLUME 추가: 회전율 활발 종목 (저가주·squeeze 후보)

    각 타입에서 rank 별도 저장 · 최적 rank(=최소값) 만 사용 (in-memory dedup).

    Returns:
        {"total_ranked": N, "universe_matched": M, "saved": K, "per_type": {...}}
    """
    client = toss_client or get_toss_client()
    now = datetime.now(tz=timezone.utc)

    # 1) 유니버스 티커 집합
    async with get_session() as session:
        urows = (await session.execute(select(LiveTapeUniverse.ticker))).all()
        universe = {r[0] for r in urows}

    # 2) 3개 타입 조회 · 티커별 최적 rank 산출
    per_type: dict[str, int] = {}
    best: dict[str, dict] = {}   # ticker → {rank, volume_amount, price, return_pct}
    for rtype in _RANKING_TYPES:
        try:
            env = client.rankings(type=rtype, count=100)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rankings(%s) 실패 · %s", rtype, exc)
            per_type[rtype] = 0
            continue
        result = env.result if isinstance(env.result, dict) else {}
        items = result.get("rankings") or []
        matched = 0
        for item in items:
            ticker = item.get("symbol")
            if not ticker or ticker not in universe:
                continue
            matched += 1
            price = item.get("price") or {}
            new_rank = int(item.get("rank")) if item.get("rank") else 999
            prev = best.get(ticker)
            if prev is None or new_rank < prev["rank"]:
                best[ticker] = {
                    "rank": new_rank,
                    "volume_amount": float(item.get("tradingAmount", 0) or 0),
                    "price": float(price.get("lastPrice", 0) or 0) or None,
                    "return_pct": float(price.get("changeRate", 0) or 0) or None,
                }
        per_type[rtype] = matched

    # 3) DB 저장 (티커당 1건 · 최적 rank)
    saved = 0
    async with get_session() as session:
        for ticker, info in best.items():
            entry = LiveTapeRanking(
                ticker=ticker,
                rank=info["rank"],
                volume_amount=info["volume_amount"],
                price=info["price"],
                return_pct=info["return_pct"],
                captured_at=now,
            )
            session.add(entry)
            saved += 1

    stats = {
        "per_type": per_type,
        "universe_matched": len(best),
        "saved": saved,
        "captured_at": now.isoformat(),
    }
    logger.info("rankings poll · types=%s · saved=%d", per_type, saved)
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


async def tickers_with_snapshots(window_sec: int = 600) -> list[str]:
    """최근 window 내 rankings 스냅샷이 있는 티커 목록 (스냅샷 개수 desc).

    scan_and_enter · candidates API 가 스캔 대상 선정에 사용.
    시총 정렬이 아닌 실제 rankings 매치 종목만 대상 → rank_velocity 유효.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=window_sec)
    from sqlalchemy import func as _func
    async with get_session() as session:
        stmt = (
            select(LiveTapeRanking.ticker, _func.count().label("cnt"))
            .where(LiveTapeRanking.captured_at >= since)
            .group_by(LiveTapeRanking.ticker)
            .order_by(_func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows]


async def cleanup_old_snapshots(keep_hours: int = 6) -> int:
    """오래된 스냅샷 정리 · 오늘 세션만 유지 (하루 최대 3600 * 6 = 21,600건 상한 근사)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=keep_hours)
    async with get_session() as session:
        stmt = delete(LiveTapeRanking).where(LiveTapeRanking.captured_at < cutoff)
        result = await session.execute(stmt)
    return int(result.rowcount or 0)
