"""Meme Watch Top N — apewisdom universe → score → 상위 N (Phase 1e).

apewisdom 최신 snapshot 의 mention 상위 종목들을 baseline 으로
volume_snapshot · oversold 시그널 join 후 score 산출.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession


from backend.discovery.meme_watch.catalyst_signal import get_catalyst_scores
from backend.discovery.meme_watch.confluence import MemeScore, compute_meme_score
from backend.discovery.meme_watch.filters import is_blacklisted
from backend.discovery.meme_watch.intensity import compute_intensity
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


async def _latest_trends_snapshot(session: AsyncSession) -> dict[str, int]:
    """최신 Google Trends batch — {ticker: score_24h (0~100)}. Phase 3-C."""
    latest_at = (
        await session.execute(
            select(MemeSocialSignal.fetched_at)
            .where(MemeSocialSignal.source == "google_trends")
            .order_by(desc(MemeSocialSignal.fetched_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_at is None:
        return {}
    rows = (
        await session.execute(
            select(MemeSocialSignal.ticker, MemeSocialSignal.mention_count)
            .where(
                MemeSocialSignal.source == "google_trends",
                MemeSocialSignal.fetched_at == latest_at,
            )
        )
    ).all()
    # trends 의 mention_count 필드 = score_24h (0~100)
    return {r[0]: int(r[1]) for r in rows}


async def _latest_volume_snapshots(
    session: AsyncSession, tickers: list[str]
) -> dict[str, MemeVolumeSnapshot]:
    """각 ticker 의 최신 volume_snapshot 일괄 — subquery + JOIN.

    Phase 2-C: KRX universe 통합으로 ticker 수 ↑ → ticker별 N+1 query 회피.
    """
    if not tickers:
        return {}
    subq = (
        select(
            MemeVolumeSnapshot.ticker,
            func.max(MemeVolumeSnapshot.snapshot_at).label("max_at"),
        )
        .where(MemeVolumeSnapshot.ticker.in_(tickers))
        .group_by(MemeVolumeSnapshot.ticker)
        .subquery()
    )
    rows = (
        await session.execute(
            select(MemeVolumeSnapshot).join(
                subq,
                (MemeVolumeSnapshot.ticker == subq.c.ticker)
                & (MemeVolumeSnapshot.snapshot_at == subq.c.max_at),
            )
        )
    ).scalars().all()
    return {r.ticker: r for r in rows}


async def _universe_meta(
    session: AsyncSession, tickers: list[str]
) -> dict[str, MemeUniverse]:
    """ticker → MemeUniverse row (active 종목만 — deactivated 노출 방지)."""
    if not tickers:
        return {}
    rows = (
        await session.execute(
            select(MemeUniverse).where(
                MemeUniverse.ticker.in_(tickers),
                MemeUniverse.is_active.is_(True),
            )
        )
    ).scalars().all()
    return {r.ticker: r for r in rows}


async def compute_top_memes(
    top_n: int = 20, market: Optional[str] = None
) -> list[dict]:
    """US (apewisdom + volume) + KRX (volume only) → score → 상위 N.

    Phase 2-C — KRX universe 종목도 score 산출 대상 (social 시그널 부재 →
    가중치 동적 재정규화: volume 0.625 / momentum 0.375).
    Phase 3-D fix — market 필터는 score 산출 후 정렬 전 적용 (정확한 top N).
    """
    async with get_session() as session:
        social = await _latest_apewisdom_snapshot(session)
        trends = await _latest_trends_snapshot(session)  # Phase 3-C
        # KRX universe 종목 (active)
        krx_rows = (
            await session.execute(
                select(MemeUniverse.ticker).where(
                    MemeUniverse.market == "KRX",
                    MemeUniverse.is_active.is_(True),
                )
            )
        ).scalars().all()
        krx_tickers = set(t for t in krx_rows if t)

        # 후보 ticker — US (apewisdom ∪ trends) ∪ KRX (universe)
        candidate_tickers = set(social.keys()) | set(trends.keys()) | krx_tickers
        if not candidate_tickers:
            logger.warning("[meme_top] no candidate tickers")
            return []

        all_list = list(candidate_tickers)
        volumes = await _latest_volume_snapshots(session, all_list)
        metas = await _universe_meta(session, all_list)

    # 외부 catalyst (DART) — KRX 종목 24h 카운트 → catalyst_score (Phase 3-B)
    catalysts = await get_catalyst_scores(all_list, hours=24)

    results = []
    for ticker in candidate_tickers:
        # ETF / 펀드 블랙리스트 제외 (Phase 3-A)
        if is_blacklisted(ticker):
            continue
        soc = social.get(ticker)
        tr = trends.get(ticker)
        vol = volumes.get(ticker)
        meta = metas.get(ticker)
        cat = catalysts.get(ticker)
        # Google Trends 만 있는 종목은 soc dict 로 승격 (Phase 3-C)
        if soc is None and tr is not None:
            soc = {"mentions": 0, "mentions_24h_ago": None, "upvotes": 0}
        if soc is not None and tr is not None:
            soc = {**soc, "trends_score_24h": tr}
        # 시그널이 하나도 없으면 skip
        if soc is None and vol is None and cat is None:
            continue
        score = compute_meme_score(
            ticker=ticker,
            social_inputs=soc,
            volume_z_20d=(vol.volume_z_20d if vol else None),
            volume_ratio_20d=(vol.volume_ratio_20d if vol else None),
            rsi_14=(vol.rsi_14 if vol else None),
            return_1d_pct=(vol.return_1d_pct if vol else None),
            catalyst_score=cat,
        )
        results.append({"score": score, "meta": meta, "volume": vol})

    results.sort(key=lambda r: r["score"].score, reverse=True)

    # market 필터 — 정렬 후 필터 → 정확한 top N (전체 candidate 대비)
    if market:
        results = [
            r for r in results
            if r.get("meta") is not None and r["meta"].market == market
        ]

    top_slice = results[:top_n]

    # Intensity 계산 — top_slice 만 (Phase 4: current_score 전달로 score_delta 활성)
    async with get_session() as session:
        for r in top_slice:
            r["intensity"] = await compute_intensity(
                session, r["score"].ticker, current_score=r["score"].score
            )

    return top_slice
