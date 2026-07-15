"""News RSS Crawler · Sprint 2 T54.

5개 언론 RSS 5분 폴링 · matcher 로 종목 매칭 · watchlist_signal 저장.

RSS URL 실측 (2026-07-13):
  · 연합인포맥스 · news.einfomax.co.kr/rss/S1N2.xml       (200)
  · 이데일리     · rss.edaily.co.kr/stock_news.xml         (200)
  · 파이낸셜뉴스 · fnnews.com/rss/r20/fn_realnews_stock.xml (200)
  · 한국경제     · hankyung.com/feed/finance               (200)
  · 연합뉴스     · yna.co.kr/rss/economy.xml               (200)

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T54
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import feedparser
import httpx

from .matcher import get_matcher
from .store import upsert_signal

logger = logging.getLogger(__name__)


RSS_SOURCES: dict[str, str] = {
    "news_yhap": "https://news.einfomax.co.kr/rss/S1N2.xml",
    "news_edaily": "https://rss.edaily.co.kr/stock_news.xml",
    "news_fnnews": "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml",
    "news_hankyung": "https://www.hankyung.com/feed/finance",
    "news_yonhap": "https://www.yna.co.kr/rss/economy.xml",
}

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1 Safari/537 TossTradebot/1.0"
_TIMEOUT_SEC = 8
_HEADLINE_LOOKBACK_HOURS = 2   # 최근 2시간 이내 항목만 저장 (초기 부하 방지)


async def _fetch(client: httpx.AsyncClient, source: str, url: str) -> Optional[str]:
    try:
        resp = await client.get(url, timeout=_TIMEOUT_SEC, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning("[news_rss] fetch %s · HTTP %s", source, resp.status_code)
            return None
        return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("[news_rss] fetch %s · %s", source, exc)
        return None


def _parse_entries(source: str, xml: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(xml)
    if parsed.bozo and not parsed.entries:
        logger.warning("[news_rss] parse %s · bozo=%s", source, parsed.bozo_exception)
        return []
    return list(parsed.entries)


def _entry_time(entry: dict[str, Any]) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val is not None:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    return None


async def _process_source(
    client: httpx.AsyncClient, source: str, url: str, cutoff: datetime,
) -> dict[str, int]:
    xml = await _fetch(client, source, url)
    if xml is None:
        return {"fetched": 0, "matched": 0, "inserted": 0, "skipped_old": 0, "error": 1}

    entries = _parse_entries(source, xml)
    matcher = get_matcher()

    matched = 0
    inserted = 0
    skipped_old = 0
    for entry in entries:
        pub = _entry_time(entry)
        if pub is not None and pub < cutoff:
            skipped_old += 1
            continue
        title = str(entry.get("title") or "")
        summary = str(entry.get("summary") or entry.get("description") or "")
        link = str(entry.get("link") or "")
        text = f"{title} {summary}"
        tickers = matcher.match_text(text)
        if not tickers:
            continue
        matched += 1
        for ticker in tickers:
            row_id = await upsert_signal(
                ticker=ticker,
                source=source,
                signal_type="headline",
                intensity=1.0,
                payload={"title": title[:200], "url": link, "published": pub.isoformat() if pub else None},
                detected_at=pub or datetime.now(tz=timezone.utc),
            )
            if row_id is not None:
                inserted += 1
    return {
        "fetched": len(entries), "matched": matched, "inserted": inserted,
        "skipped_old": skipped_old, "error": 0,
    }


async def poll_news_rss() -> dict[str, Any]:
    """5개 소스 병렬 폴링 · 매칭 · 저장.

    Returns:
        {"per_source": {source: stats}, "total_inserted": N, "elapsed_sec": T}
    """
    matcher = get_matcher()
    await matcher.ensure_loaded()

    if matcher.size() == 0:
        logger.warning("[news_rss] matcher 비어있음 · universe refresh 선행 필요")
        return {"error": "empty_matcher", "matcher_size": 0}

    start = datetime.now(tz=timezone.utc)
    cutoff = start - timedelta(hours=_HEADLINE_LOOKBACK_HOURS)

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        tasks = [_process_source(client, s, u, cutoff) for s, u in RSS_SOURCES.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    per_source: dict[str, dict[str, int]] = {}
    total_inserted = 0
    for (source, _), result in zip(RSS_SOURCES.items(), results):
        if isinstance(result, Exception):
            per_source[source] = {"error": 1, "exception": str(result)[:100]}
            continue
        per_source[source] = result
        total_inserted += result.get("inserted", 0)

    elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
    logger.info("[news_rss] total_inserted=%d elapsed=%.2fs matcher=%d",
                total_inserted, elapsed, matcher.size())
    return {
        "per_source": per_source,
        "total_inserted": total_inserted,
        "matcher_size": matcher.size(),
        "elapsed_sec": elapsed,
    }
