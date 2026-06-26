"""Reddit + apewisdom (+ 후속 Stocktwits/Trends) → meme_social_signal 적재.

5분 batch (24h 윈도우 누적).

2가지 Reddit 소스 병행:
- apewisdom (1차 MVP, source="apewisdom") — 운영 IP 차단 없음, 24h 비교 데이터 제공
- Reddit 직접 (PRAW OAuth 발급 시, source="reddit") — A 신청 승인 후 활성화

[[keep_alternatives_alongside]] — 두 소스 모두 보존, A 승인 시 cross-check.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import desc, select

from backend.discovery.data_sources.apewisdom import fetch_filter as fetch_apewisdom
from backend.discovery.data_sources.google_trends import fetch_interest
from backend.discovery.data_sources.reddit import SUBREDDITS, fetch_mentions
from backend.discovery.data_sources.stocktwits import fetch_sentiment_batch
from backend.services.db import get_session
from backend.services.models import MemeSocialSignal

logger = logging.getLogger(__name__)


async def _top_apewisdom_tickers(limit: int = 100) -> list[str]:
    """가장 최근 apewisdom snapshot 의 mention 상위 N ticker."""
    async with get_session() as session:
        latest_at = (
            await session.execute(
                select(MemeSocialSignal.fetched_at)
                .where(MemeSocialSignal.source == "apewisdom")
                .order_by(desc(MemeSocialSignal.fetched_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_at is None:
            return []
        rows = (
            await session.execute(
                select(MemeSocialSignal.ticker, MemeSocialSignal.mention_count)
                .where(
                    MemeSocialSignal.source == "apewisdom",
                    MemeSocialSignal.fetched_at == latest_at,
                )
                .order_by(desc(MemeSocialSignal.mention_count))
                .limit(limit)
            )
        ).all()
    return [r[0] for r in rows]


async def build_apewisdom_signals(pages: int = 2) -> dict:
    """apewisdom all-stocks 상위 N×100 ticker → meme_social_signal 적재."""
    stats = {"tickers": 0, "saved": 0, "errors": 0}

    try:
        mentions = await fetch_apewisdom("all-stocks", pages=pages)
    except Exception as e:
        logger.exception(f"[meme_social_apewisdom] fetch failed: {e}")
        stats["errors"] = 1
        return stats

    stats["tickers"] = len(mentions)
    if not mentions:
        logger.info("[meme_social_apewisdom] no mentions returned")
        return stats

    now = datetime.now()
    async with get_session() as session:
        for m in mentions:
            session.add(
                MemeSocialSignal(
                    ticker=m.ticker,
                    source="apewisdom",
                    fetched_at=now,
                    mention_count=m.mentions,
                    weighted_score=float(m.upvotes),
                    sentiment_delta=None,  # apewisdom 미제공
                    window_hours=24,
                )
            )
            stats["saved"] += 1
        await session.commit()

    logger.info(f"[meme_social_apewisdom] done stats={stats}")
    return stats


async def build_stocktwits_signals(top_n: int = 100) -> dict:
    """apewisdom 상위 N ticker → Stocktwits sentiment fetch + 적재."""
    stats = {"target_tickers": 0, "fetched": 0, "saved": 0, "errors": 0}

    tickers = await _top_apewisdom_tickers(limit=top_n)
    stats["target_tickers"] = len(tickers)
    if not tickers:
        logger.info("[meme_social_stocktwits] no apewisdom baseline — skip")
        return stats

    try:
        sentiments = await fetch_sentiment_batch(tickers, concurrency=5)
    except Exception as e:
        logger.exception(f"[meme_social_stocktwits] batch failed: {e}")
        stats["errors"] = 1
        return stats

    stats["fetched"] = len(sentiments)
    if not sentiments:
        return stats

    now = datetime.now()
    async with get_session() as session:
        for ticker, s in sentiments.items():
            session.add(
                MemeSocialSignal(
                    ticker=ticker,
                    source="stocktwits",
                    fetched_at=now,
                    mention_count=s.total,
                    weighted_score=float(s.bullish + s.bearish),
                    sentiment_delta=s.sentiment_delta,
                    window_hours=24,
                )
            )
            stats["saved"] += 1
        await session.commit()

    logger.info(f"[meme_social_stocktwits] done stats={stats}")
    return stats


async def build_trends_signals(top_n: int = 30) -> dict:
    """apewisdom 상위 N ticker → Google Trends 검색량 fetch + 적재.

    pytrends 한도: 5 ticker / 호출 · 시간당 ~30회 권장 (Captcha 회피).
    top_n=30 = chunk 6 × 2초 = ~12초.
    """
    stats = {"target_tickers": 0, "fetched": 0, "saved": 0, "errors": 0}

    tickers = await _top_apewisdom_tickers(limit=top_n)
    stats["target_tickers"] = len(tickers)
    if not tickers:
        logger.info("[meme_social_trends] no apewisdom baseline — skip")
        return stats

    try:
        snapshots = await fetch_interest(tickers)
    except Exception as e:
        logger.exception(f"[meme_social_trends] fetch failed: {e}")
        stats["errors"] = 1
        return stats

    stats["fetched"] = len(snapshots)
    if not snapshots:
        return stats

    now = datetime.now()
    async with get_session() as session:
        for ticker, snap in snapshots.items():
            session.add(
                MemeSocialSignal(
                    ticker=ticker,
                    source="google_trends",
                    fetched_at=now,
                    mention_count=snap.score_24h,
                    weighted_score=snap.score_avg,
                    sentiment_delta=None,
                    window_hours=24,
                )
            )
            stats["saved"] += 1
        await session.commit()

    logger.info(f"[meme_social_trends] done stats={stats}")
    return stats


async def build_reddit_signals(hours: int = 24) -> dict:
    """Reddit 4 subreddit (24h 윈도우) → ticker별 mention + upvote 가중."""
    stats = {
        "subreddits": len(SUBREDDITS),
        "total_mentions": 0,
        "unique_tickers": 0,
        "saved": 0,
        "errors": 0,
    }

    try:
        mentions = await fetch_mentions(SUBREDDITS, hours=hours)
    except Exception as e:
        logger.exception(f"[meme_social_reddit] fetch_mentions failed: {e}")
        stats["errors"] = 1
        return stats

    stats["total_mentions"] = len(mentions)
    if not mentions:
        logger.info("[meme_social_reddit] no mentions in window")
        return stats

    # ticker별 집계 — count + (score 합 — 음수 보정해 max 0)
    by_ticker: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "weighted": 0.0}
    )
    for m in mentions:
        by_ticker[m.ticker]["count"] += 1
        by_ticker[m.ticker]["weighted"] += max(0, m.score)

    stats["unique_tickers"] = len(by_ticker)

    now = datetime.now()
    async with get_session() as session:
        for ticker, agg in by_ticker.items():
            session.add(
                MemeSocialSignal(
                    ticker=ticker,
                    source="reddit",
                    fetched_at=now,
                    mention_count=int(agg["count"]),
                    weighted_score=float(agg["weighted"]),
                    sentiment_delta=None,
                    window_hours=hours,
                )
            )
            stats["saved"] += 1
        await session.commit()

    logger.info(f"[meme_social_reddit] done stats={stats}")
    return stats
