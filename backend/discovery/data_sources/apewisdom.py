"""ApeWisdom 클라이언트 — F4 소셜 sentiment (Reddit 대체, 결정 2026-06-19).

배경:
- 2025-11-11 Reddit "Responsible Builder Policy" 시행 → 모든 API 접근 사전 승인 필수
  (2-4주 소요). 단순 prefs/apps create 불가.
- ApeWisdom 은 무료·무인증 — r/wallstreetbets · stocks · investing 등 12+
  subreddit + 4chan /biz/ 멘션을 30분마다 집계해 JSON 으로 노출.
- 가중치는 결정 32 그대로 (소셜 8%) — 학술적 알파 의미 동일 (단순 멘션 카운트).

API:
- Base: https://apewisdom.io/api/v1.0
- Endpoint: /filter/{filter}/page/{n}  (filter: wallstreetbets / all-stocks / ...)
- 인증·rate limit 명시 X (관용적 무료)

응답:
{
  "count": 817, "pages": 9, "current_page": 1,
  "results": [
    {"rank": 1, "ticker": "NVDA", "name": "Nvidia",
     "mentions": "234", "upvotes": "1024",
     "rank_24h_ago": "3", "mentions_24h_ago": "188"}
  ]
}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.discovery.data_sources.base import DataSourceClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MentionStats:
    """티커별 멘션 통계 (24h 윈도우). Reddit RedditMentionStats 와 호환."""

    ticker: str
    subreddit: str         # "wallstreetbets" 또는 "all-stocks"
    window_hours: int      # 24 (ApeWisdom 기본)
    mention_count: int     # 현재 24h
    mentions_24h_ago: int  # 전일 24h
    upvotes: int
    rank: Optional[int]    # 현재 순위
    rank_24h_ago: Optional[int]
    trend_up: bool         # 멘션 증가 추세 (전일 대비)


class ApewisdomClient(DataSourceClient):
    """ApeWisdom 무인증 클라이언트."""

    BASE_URL = "https://apewisdom.io/api/v1.0"
    DEFAULT_FILTER = "wallstreetbets"
    MAX_PAGES = 3  # 300 ticker 까지 — universe 대다수 커버

    def __init__(self) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            headers={
                "User-Agent": "toss-tradebot-mvp/0.1",
                "Accept": "application/json",
            },
        )
        # 캐시: {(filter, page): {ticker: dict}}
        self._cache: dict[str, dict[str, dict]] = {}

    async def fetch_trending(
        self,
        filter_name: str = DEFAULT_FILTER,
        max_pages: int = MAX_PAGES,
    ) -> dict[str, dict]:
        """전체 trending ticker dict 반환 (ticker → fields)."""
        if filter_name in self._cache:
            return self._cache[filter_name]

        merged: dict[str, dict] = {}
        for page in range(1, max_pages + 1):
            path = f"/filter/{filter_name}/page/{page}"
            try:
                response = await self.get(path)
            except Exception as e:
                logger.debug(f"[ApeWisdom] page {page} fetch fail: {e}")
                break

            data = response.json()
            results = data.get("results", [])
            if not results:
                break
            for entry in results:
                ticker = entry.get("ticker", "").upper()
                if ticker:
                    merged[ticker] = entry

            # 마지막 페이지 도달 시 break
            total_pages = data.get("pages", 1)
            if page >= total_pages:
                break

        self._cache[filter_name] = merged
        logger.info(f"[ApeWisdom] {filter_name} loaded {len(merged)} tickers")
        return merged

    async def get_mention_stats(
        self,
        ticker: str,
        filter_name: str = DEFAULT_FILTER,
    ) -> MentionStats:
        """티커 단일 멘션 통계 (없으면 0)."""
        trending = await self.fetch_trending(filter_name)
        entry = trending.get(ticker.upper())

        if not entry:
            return MentionStats(
                ticker=ticker.upper(),
                subreddit=filter_name,
                window_hours=24,
                mention_count=0,
                mentions_24h_ago=0,
                upvotes=0,
                rank=None,
                rank_24h_ago=None,
                trend_up=False,
            )

        def _int(v) -> int:
            try:
                return int(v)
            except (ValueError, TypeError):
                return 0

        mentions = _int(entry.get("mentions"))
        mentions_prev = _int(entry.get("mentions_24h_ago"))
        upvotes = _int(entry.get("upvotes"))
        rank = _int(entry.get("rank")) or None
        rank_prev = _int(entry.get("rank_24h_ago")) or None

        return MentionStats(
            ticker=ticker.upper(),
            subreddit=filter_name,
            window_hours=24,
            mention_count=mentions,
            mentions_24h_ago=mentions_prev,
            upvotes=upvotes,
            rank=rank,
            rank_24h_ago=rank_prev,
            trend_up=mentions > mentions_prev,
        )
