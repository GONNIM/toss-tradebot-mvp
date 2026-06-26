"""Reddit (+ 후속 Stocktwits/Trends) mention → meme_social_signal 적재.

5분 batch (장중 / 24h 윈도우 누적).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from backend.discovery.data_sources.reddit import SUBREDDITS, fetch_mentions
from backend.services.db import get_session
from backend.services.models import MemeSocialSignal

logger = logging.getLogger(__name__)


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
