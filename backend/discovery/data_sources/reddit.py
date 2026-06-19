"""Reddit PRAW 클라이언트 — F4 소셜 sentiment (결정 14·32).

- 무료 60 req/min
- script app 등록 필요 (reddit.com/prefs/apps)
- WallStreetBets subreddit 24h 멘션 카운트

학술 검증 (moonshot-factor-research.md §1.4):
- WSB sentiment 알파 약함 (BUZZ ETF S&P 대비 -15%)
- **단순 멘션 카운트** + 가격 모멘텀 결합 시 효과
- 따라서 sentiment 분석 X — 멘션 수만 사용

가중치 (결정 32 학술 검증 후): 8%
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedditMentionStats:
    """Reddit 멘션 통계 (24h 윈도우)."""

    ticker: str
    subreddit: str
    window_hours: int
    mention_count: int
    avg_score: float           # 평균 upvote
    distinct_authors: int
    top_post_title: Optional[str]
    top_post_score: int


# Cashtag 패턴: $AAPL, $NVDA 등 (대문자 1~5자)
CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
# Plain ticker mention (단어 경계 내, 대문자 3~5자) — 노이즈 많아 보조
TICKER_RE = re.compile(r"\b([A-Z]{3,5})\b")


class RedditClient:
    """PRAW 기반 Reddit 클라이언트.

    PRAW는 자체 client 관리 — DataSourceClient base 와 다른 구조.
    """

    DEFAULT_SUBREDDIT = "wallstreetbets"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("REDDIT_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("REDDIT_CLIENT_SECRET", "")
        self.user_agent = user_agent or os.environ.get(
            "REDDIT_USER_AGENT", "toss-tradebot-mvp/0.1"
        )
        self._reddit = None  # praw.Reddit instance, lazy init

    def _ensure_reddit(self):
        """PRAW 인스턴스 lazy 초기화."""
        if self._reddit is not None:
            return self._reddit

        try:
            import praw  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "praw 미설치. `pip install praw` 또는 `pip install -e .[dev]`"
            ) from e

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 미설정. "
                ".env 에 추가 필요 (reddit.com/prefs/apps script 앱 등록)"
            )

        import praw
        self._reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
        )
        # Read-only mode (인증 없음)
        self._reddit.read_only = True
        return self._reddit

    def get_mention_stats(
        self,
        ticker: str,
        subreddit: str = DEFAULT_SUBREDDIT,
        window_hours: int = 24,
        max_posts: int = 200,
    ) -> RedditMentionStats:
        """티커 멘션 통계 (24h 윈도우, 단순 카운트).

        Note: PRAW는 async 미지원 — sync 호출. Phase D 에서 asyncio.to_thread 로 감쌈.
        """
        reddit = self._ensure_reddit()
        sub = reddit.subreddit(subreddit)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

        ticker_upper = ticker.upper()
        cashtag = f"${ticker_upper}"

        mentions = 0
        scores = []
        authors = set()
        top_post = None
        top_score = 0

        for post in sub.new(limit=max_posts):
            created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
            if created < cutoff:
                continue

            text = (post.title or "") + " " + (post.selftext or "")
            # cashtag 우선 (정확도 高)
            has_cashtag = cashtag in text.upper()
            has_plain = bool(re.search(rf"\b{ticker_upper}\b", text.upper())) if not has_cashtag else False

            if has_cashtag or has_plain:
                mentions += 1
                scores.append(post.score)
                authors.add(str(post.author) if post.author else "deleted")
                if post.score > top_score:
                    top_score = post.score
                    top_post = post.title

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return RedditMentionStats(
            ticker=ticker_upper,
            subreddit=subreddit,
            window_hours=window_hours,
            mention_count=mentions,
            avg_score=avg_score,
            distinct_authors=len(authors),
            top_post_title=top_post,
            top_post_score=top_score,
        )
