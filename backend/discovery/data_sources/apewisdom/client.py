"""apewisdom.io API client — Reddit ticker mention aggregator.

URL: https://apewisdom.io/api/v1.0/filter/{filter_name}/page/{N}
Filters: wallstreetbets / stocks / pennystocks / options / cryptocurrency /
         all-stocks (multiple subs combined — 권장)
Page size: 100 results / page

응답 (단일 entry):
    {
      "rank": 1,
      "ticker": "MU",
      "name": "Micron Technology",
      "mentions": 1338,
      "upvotes": 5857,
      "rank_24h_ago": 1,
      "mentions_24h_ago": 2503
    }

핵심 가치: mentions_24h_ago / rank_24h_ago 제공 — z-score baseline 즉시
산출 가능. Reddit 직접 fetch 시 30일 평균 별도 누적 필요했으나, apewisdom
은 24h 비교 데이터를 자체 보유.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://apewisdom.io/api/v1.0"
_UA = "toss-tradebot-mvp:meme-watch:v0.1"
_TIMEOUT_SEC = 10.0


@dataclass(frozen=True)
class ApeWisdomMention:
    ticker: str
    name: str
    rank: int
    mentions: int
    upvotes: int
    rank_24h_ago: Optional[int]
    mentions_24h_ago: Optional[int]


async def fetch_filter(
    filter_name: str = "all-stocks", pages: int = 2
) -> list[ApeWisdomMention]:
    """apewisdom 필터별 상위 N pages × 100 ticker fetch.

    Args:
        filter_name: "all-stocks" (권장, 다중 subreddit 통합) /
                     "wallstreetbets" / "stocks" / "pennystocks" / "options"
        pages: fetch 할 page 수 (1=100, 2=200, ...). mention desc 정렬이라
               상위 200 이면 의미있는 시그널 모두 커버.
    """
    result: list[ApeWisdomMention] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, pages + 1):
            url = f"{_BASE}/filter/{filter_name}/page/{page}"
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": _UA},
                    timeout=_TIMEOUT_SEC,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(
                    f"[apewisdom] {filter_name} page {page} failed: {e}"
                )
                continue

            for r in data.get("results", []):
                try:
                    result.append(
                        ApeWisdomMention(
                            ticker=str(r["ticker"]).strip().upper(),
                            name=str(r.get("name") or "").strip(),
                            rank=int(r["rank"]),
                            mentions=int(r["mentions"]),
                            upvotes=int(r.get("upvotes") or 0),
                            rank_24h_ago=(
                                int(r["rank_24h_ago"])
                                if r.get("rank_24h_ago") is not None
                                else None
                            ),
                            mentions_24h_ago=(
                                int(r["mentions_24h_ago"])
                                if r.get("mentions_24h_ago") is not None
                                else None
                            ),
                        )
                    )
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"[apewisdom] parse entry failed: {e}")

            # 마지막 page 도달 시 중단
            total_pages = int(data.get("pages") or 1)
            if page >= total_pages:
                break

    logger.info(
        f"[apewisdom] {filter_name}: {len(result)} mentions ({pages} pages)"
    )
    return result
