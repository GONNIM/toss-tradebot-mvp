"""Meme Score 이력 자동 저장 (Phase 4).

매 5분 batch (apewisdom 후 offset)로 top N 종목 score 를 MemeScoreHistory
에 저장. Intensity 의 score_delta / Time-in-BLAZING / persistence 시그널
계산 baseline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_session
from backend.services.models import MemeScoreHistory

logger = logging.getLogger(__name__)


async def build_score_history(top_n: int = 100) -> dict:
    """현재 top N 종목 score 를 MemeScoreHistory 에 적재."""
    from backend.discovery.meme_watch.top import compute_top_memes

    stats = {"saved": 0}
    results = await compute_top_memes(top_n=top_n)
    if not results:
        return stats

    now = datetime.now()
    async with get_session() as session:
        for r in results:
            score = r["score"]
            meta = r.get("meta")
            session.add(
                MemeScoreHistory(
                    ticker=score.ticker,
                    snapshot_at=now,
                    market=(meta.market if meta else None),
                    score=float(score.score),
                    label=score.label,
                    active_signals=score.active_signals,
                )
            )
            stats["saved"] += 1
        await session.commit()

    logger.info(f"[meme_score_history] done stats={stats}")
    return stats


async def get_score_delta_24h(
    session: AsyncSession, ticker: str, current_score: float
) -> Optional[float]:
    """24h 전 score 대비 delta.

    Returns: current − 24h_ago (None if 이력 부재).
    """
    cutoff = datetime.now() - timedelta(hours=24)
    tolerance = timedelta(hours=3)  # 24h 전후 3h 여유

    row = (
        await session.execute(
            select(MemeScoreHistory.score)
            .where(
                MemeScoreHistory.ticker == ticker,
                MemeScoreHistory.snapshot_at >= cutoff - tolerance,
                MemeScoreHistory.snapshot_at <= cutoff + tolerance,
            )
            .order_by(desc(MemeScoreHistory.snapshot_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return current_score - float(row)


async def get_time_in_blazing(
    session: AsyncSession, ticker: str, days: int = 7
) -> int:
    """최근 N일 중 label='BLAZING' 또는 'HOT' snapshot 개수."""
    cutoff = datetime.now() - timedelta(days=days)
    count = (
        await session.execute(
            select(func.count())
            .select_from(MemeScoreHistory)
            .where(
                MemeScoreHistory.ticker == ticker,
                MemeScoreHistory.snapshot_at >= cutoff,
                MemeScoreHistory.label.in_(["BLAZING", "HOT"]),
            )
        )
    ).scalar()
    return int(count or 0)
