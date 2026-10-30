"""News RSS Crawler · Sprint 2 T54.

언론 RSS 9개 5분 폴링 · matcher.match_news 로 종목 매칭 · watchlist_signal 저장.

RSS URL (2026-07-13 실측 5곳 + 1030-04 추가 5곳 · 이데일리는 TLS 1.0 · 10/28 피드 멈춤으로 제거):
  · 연합인포맥스 증권 · news.einfomax.co.kr/rss/S1N2.xml
  · 연합인포맥스 전체 · news.einfomax.co.kr/rss/allArticle.xml
  · 파이낸셜뉴스      · fnnews.com/rss/r20/fn_realnews_stock.xml
  · 한국경제          · hankyung.com/feed/finance
  · 연합뉴스 경제     · yna.co.kr/rss/economy.xml
  · 연합뉴스 마켓     · yna.co.kr/rss/market.xml
  · 매일경제 증권     · mk.co.kr/rss/50200011/
  · 서울경제 금융     · sedaily.com/rss/finance
  · 이투데이 금융     · rss.etoday.co.kr/eto/finance_news.xml
같은 언론의 두 피드가 같은 기사를 올려도 URL 중복 제거(store)가 출처 무관으로 한 번만 센다.

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T54
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import feedparser
import httpx

from .matcher import get_matcher
from .store import upsert_signal

logger = logging.getLogger(__name__)


RSS_SOURCES: dict[str, str] = {
    "news_yhap": "https://news.einfomax.co.kr/rss/S1N2.xml",
    "news_fnnews": "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml",
    "news_hankyung": "https://www.hankyung.com/feed/finance",
    "news_yonhap": "https://www.yna.co.kr/rss/economy.xml",
    "news_mk": "https://www.mk.co.kr/rss/50200011/",
    "news_sedaily": "https://www.sedaily.com/rss/finance",
    "news_yna_market": "https://www.yna.co.kr/rss/market.xml",
    "news_etoday": "https://rss.etoday.co.kr/eto/finance_news.xml",
    "news_einfomax_all": "https://news.einfomax.co.kr/rss/allArticle.xml",
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


_KST = timezone(timedelta(hours=9))


def _parse_pub_str(raw: str) -> Optional[datetime]:
    """피드 원문 발행시각 → UTC (1030-02).

    · fnnews 는 「Fri,30 Oct 2026 06:00:00 +0900」 처럼 쉼표 뒤 공백이 없어 feedparser 가 못 읽는다
    · 연합인포맥스는 「2026-10-30 10:18:00」 처럼 시간대가 없다 → 국내 피드라 KST 로 본다
    · 「Fri, 30 Oct 2026 17:46:01 +09:00」 은 콜론을 빼 읽는다 (1030-04)
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    # 「+09:00」(콜론 오프셋) 은 parsedate_to_datetime 이 시간대를 못 읽고 UTC 로 둔다 → 「+0900」 으로 (1030-04)
    raw = re.sub(r"\s([+-])(\d{2}):(\d{2})$", r" \1\2\3", raw)
    try:
        dt = parsedate_to_datetime(re.sub(r",(?=\S)", ", ", raw))
        if dt.tzinfo is None:  # RFC 822 「-0000」 = UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    return dt.astimezone(timezone.utc)


def _entry_time(entry: dict[str, Any]) -> Optional[datetime]:
    # 원문 문자열 우선 · feedparser *_parsed 는 시간대 없는 값을 UTC 로 읽어 9시간 어긋난다
    for key in ("published", "updated"):
        val = entry.get(key)
        if isinstance(val, str):
            dt = _parse_pub_str(val)
            if dt is not None:
                return dt
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
        # 뉴스 전용 매칭 (오탐 규칙 · 별칭 · 다종목 분산) · intensity = 가중 (1030-04)
        weighted = matcher.match_news(title, summary)
        if not weighted:
            continue
        matched += 1
        for ticker, weight in weighted:
            row_id = await upsert_signal(
                ticker=ticker,
                source=source,
                signal_type="headline",
                intensity=weight,
                payload={"title": title[:200], "url": link, "published": pub.isoformat() if pub else None},
                detected_at=pub or datetime.now(tz=timezone.utc),
                dedup_url=link or None,
            )
            if row_id is not None:
                inserted += 1
    return {
        "fetched": len(entries), "matched": matched, "inserted": inserted,
        "skipped_old": skipped_old, "error": 0,
    }


async def poll_news_rss() -> dict[str, Any]:
    """RSS 소스 병렬 폴링 · 매칭 · 저장.

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
