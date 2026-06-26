"""Meme Watch Top N — apewisdom universe → score → 상위 N (Phase 1e).

apewisdom 최신 snapshot 의 mention 상위 종목들을 baseline 으로
volume_snapshot · oversold 시그널 join 후 score 산출.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.meme_watch.confluence import MemeScore, compute_meme_score
from backend.services.db import get_session
from backend.services.models import (
    MemeSocialSignal,
    MemeUniverse,
    MemeVolumeSnapshot,
)

logger = logging.getLogger(__name__)


async def _latest_apewisdom_snapshot(session: AsyncSession) -> dict[str, dict]:
    """최신 apewisdom batch — {ticker: {mentions, mentions_24h_ago, upvotes}}."""
    latest_at = (
        await session.execute(
            select(MemeSocialSignal.fetched_at)
            .where(MemeSocialSignal.source == "apewisdom")
            .order_by(desc(MemeSocialSignal.fetched_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_at is None:
        return {}
    rows = (
        await session.execute(
            select(MemeSocialSignal)
            .where(
                MemeSocialSignal.source == "apewisdom",
                MemeSocialSignal.fetched_at == latest_at,
            )
        )
    ).scalars().all()
    out: dict[str, dict] = {}
    for r in rows:
        out[r.ticker] = {
            "mentions": r.mention_count,
            "mentions_24h_ago": None,  # apewisdom 은 별도 필드 — 현재 schema 미저장
            "upvotes": r.weighted_score,
        }
    return out


async def _latest_volume_snapshots(
    session: AsyncSession, tickers: list[str]
) -> dict[str, MemeVolumeSnapshot]:
    """각 ticker 의 최신 volume_snapshot row."""
    if not tickers:
        return {}
    out: dict[str, MemeVolumeSnapshot] = {}
    for t in tickers:
        row = (
            await session.execute(
                select(MemeVolumeSnapshot)
                .where(MemeVolumeSnapshot.ticker == t)
                .order_by(desc(MemeVolumeSnapshot.snapshot_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            out[t] = row
    return out


async def _universe_meta(
    session: AsyncSession, tickers: list[str]
) -> dict[str, MemeUniverse]:
    """ticker → MemeUniverse row (name/market/sector/market_cap)."""
    if not tickers:
        return {}
    rows = (
        await session.execute(
            select(MemeUniverse).where(MemeUniverse.ticker.in_(tickers))
        )
    ).scalars().all()
    return {r.ticker: r for r in rows}


async def compute_top_memes(top_n: int = 20) -> list[dict]:
    """apewisdom Top → 시그널 join → score 산출 → 상위 N.

    Returns:
        list of dict {meta, score: MemeScore}. score 내림차순.
    """
    async with get_session() as session:
        social = await _latest_apewisdom_snapshot(session)
        if not social:
            logger.warning("[meme_top] apewisdom snapshot 없음")
            return []

        tickers = list(social.keys())
        volumes = await _latest_volume_snapshots(session, tickers)
        metas = await _universe_meta(session, tickers)

    results = []
    for ticker, soc in social.items():
        vol = volumes.get(ticker)
        meta = metas.get(ticker)
        score = compute_meme_score(
            ticker=ticker,
            social_inputs=soc,
            volume_z_20d=(vol.volume_z_20d if vol else None),
            rsi_14=(vol.rsi_14 if vol else None),
            return_1d_pct=(vol.return_1d_pct if vol else None),
        )
        results.append({"score": score, "meta": meta, "volume": vol})

    # score desc 정렬
    results.sort(key=lambda r: r["score"].score, reverse=True)
    return results[:top_n]
