"""Reddit 공개 JSON endpoint — 무인증, 60 QPM rate limit.

URL 패턴:
    GET https://www.reddit.com/r/{subreddit}/new.json?limit=100
    GET https://www.reddit.com/r/{subreddit}/top.json?t=day&limit=100

응답 구조:
    {
      "data": {
        "children": [
          {"data": {
            "id": "...", "title": "...", "selftext": "...",
            "score": int, "created_utc": float, "permalink": "...",
            "subreddit": "..."
          }}, ...
        ]
      }
    }

정책 부합 (Responsible Builder Policy 2025-11~):
- 공개 데이터만 fetch (private DM/vote/post 사용 X)
- 비상업적, 개인 사용
- Rate limit 준수 (60 QPM IP 기준, 우리는 0.8 QPM 사용)
- 명시적 User-Agent (계정/앱명 포함)
- 본문 원문 저장 안 함 — ticker mention 통계만 산출
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://www.reddit.com"
_UA = "toss-tradebot-mvp:meme-watch:v0.1 (by /u/Gonnim)"
_TIMEOUT_SEC = 10.0
_BETWEEN_SUB_SEC = 1.0  # rate limit 안전 마진 — subreddit 사이 sleep

# 모니터 대상 — 02 plan 합의 4개
SUBREDDITS = ["wallstreetbets", "stocks", "pennystocks", "Shortsqueeze"]

# $TICKER (1~5자 대문자) — 단어 경계 + 명시적 $ prefix
# 예: "$GME", "$TSLA", "$AAPL"
_TICKER_REGEX = re.compile(r"(?:^|[^A-Za-z0-9])\$([A-Z]{1,5})(?:[^A-Za-z0-9]|$)")

# ETF / index / 일반 단어 — 매칭에서 제외 (false positive 방지)
_TICKER_BLACKLIST = {
    "USD", "USA", "GDP", "CEO", "CFO", "FDA", "SEC", "IPO", "WSB", "ATH",
    "YTD", "FOMO", "FUD", "DD", "TLDR", "EV", "AI", "ML", "QQQ", "SPY",
    "DIA", "IWM", "VTI", "EOD", "GO", "WIN", "BIG", "NEW", "OLD", "PUT",
    "CALL", "LONG", "SHORT", "BUY", "SELL", "HOLD", "MOON", "BTC", "ETH",
}


@dataclass(frozen=True)
class RedditMention:
    subreddit: str
    post_id: str
    ticker: str
    score: int        # upvote (Reddit `score` 필드)
    created_utc: float
    permalink: str


async def fetch_subreddit_new(
    subreddit: str,
    limit: int = 100,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """공개 JSON endpoint — /r/{sub}/new.json?limit=N. 결과: post data list."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        url = f"{_BASE}/r/{subreddit}/new.json"
        try:
            resp = await client.get(
                url,
                params={"limit": limit, "raw_json": 1},
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 403):
                logger.warning(
                    f"[reddit] /r/{subreddit}/new rate-limit/forbidden: "
                    f"{e.response.status_code} — backoff"
                )
            else:
                logger.warning(f"[reddit] /r/{subreddit}/new HTTP error: {e}")
            return []
        except Exception as e:
            logger.warning(f"[reddit] /r/{subreddit}/new failed: {e}")
            return []

        children = data.get("data", {}).get("children", [])
        return [c.get("data", {}) for c in children]
    finally:
        if own_client:
            await client.aclose()


def extract_tickers(text: str) -> list[str]:
    """텍스트에서 $TICKER 추출 — 블랙리스트 제거.

    중복 제거 (동일 post 내 같은 ticker 한 번만).
    """
    if not text:
        return []
    tickers = set(_TICKER_REGEX.findall(text))
    return [t for t in tickers if t not in _TICKER_BLACKLIST]


async def fetch_mentions(
    subreddits: Optional[list[str]] = None,
    hours: int = 24,
    limit_per_sub: int = 100,
) -> list[RedditMention]:
    """N시간 윈도우 mention 수집 — 모든 subreddit posts → $TICKER 추출.

    rate limit 안전 마진: subreddit 사이 1초 sleep.
    """
    subreddits = subreddits or SUBREDDITS
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    mentions: list[RedditMention] = []

    async with httpx.AsyncClient() as client:
        for sub in subreddits:
            posts = await fetch_subreddit_new(sub, limit=limit_per_sub, client=client)
            in_window = 0
            for p in posts:
                created = p.get("created_utc", 0)
                if created < cutoff:
                    continue
                in_window += 1
                title = p.get("title") or ""
                selftext = p.get("selftext") or ""
                tickers = extract_tickers(f"{title} {selftext}")
                for t in tickers:
                    mentions.append(
                        RedditMention(
                            subreddit=sub,
                            post_id=p.get("id", ""),
                            ticker=t,
                            score=int(p.get("score") or 0),
                            created_utc=float(created),
                            permalink=p.get("permalink") or "",
                        )
                    )
            logger.info(
                f"[reddit] /r/{sub}: {len(posts)} posts ({in_window} in {hours}h "
                f"window) → {sum(1 for m in mentions if m.subreddit == sub)} mentions"
            )
            await asyncio.sleep(_BETWEEN_SUB_SEC)

    return mentions
