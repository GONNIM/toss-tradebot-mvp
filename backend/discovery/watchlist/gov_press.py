"""정부 부처 보도자료 · Sprint 2 T57.

⚠️ v1 제한: 산업부·과기부·국토부 RSS URL 실측 결과 대부분 404 또는 HTML 반환.
    유일 사용 가능 · 기획재정부 · https://www.moef.go.kr/rss/press.xml (2026-07-13 200 · 실제 XML 여부 재검증 필요)

v1 방침:
  1. `feedparser` 로 시도 · 파싱 실패 시 소스 skip
  2. 소스 목록은 env `GOV_RSS_SOURCES` JSON override 가능
  3. Week 2/v2 에서 웹 스크래핑 fallback 검토

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T57
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import feedparser
import httpx

from .industry_map import match_industries
from .store import upsert_signal

logger = logging.getLogger(__name__)


_DEFAULT_SOURCES: dict[str, str] = {
    "moef_rss": "https://www.moef.go.kr/rss/press.xml",
    # 산업부·과기부·국토부 · TBD (URL 실측 실패 · Week 2 재조사)
}

_USER_AGENT = "Mozilla/5.0 TossTradebot/1.0"
_TIMEOUT_SEC = 8
_LOOKBACK_HOURS = 24


def _resolve_sources() -> dict[str, str]:
    override = os.environ.get("GOV_RSS_SOURCES", "").strip()
    sources = dict(_DEFAULT_SOURCES)
    if override:
        try:
            sources.update(json.loads(override))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[gov_press] GOV_RSS_SOURCES parse 실패 · %s", exc)
    return {k: v for k, v in sources.items() if v}


def _entry_time(entry: dict[str, Any]) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val is not None:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    return None


async def _process(
    client: httpx.AsyncClient, source: str, url: str, cutoff: datetime,
) -> dict[str, int]:
    try:
        resp = await client.get(url, timeout=_TIMEOUT_SEC, follow_redirects=True)
        if resp.status_code != 200:
            return {"fetched": 0, "matched": 0, "inserted": 0, "error": 1}
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        logger.debug("[gov_press] %s · %s", source, exc)
        return {"fetched": 0, "matched": 0, "inserted": 0, "error": 1}

    parsed = feedparser.parse(text)
    if parsed.bozo and not parsed.entries:
        return {"fetched": 0, "matched": 0, "inserted": 0, "error": 1}

    entries = list(parsed.entries)
    matched = 0
    inserted = 0
    for entry in entries:
        pub = _entry_time(entry)
        if pub is not None and pub < cutoff:
            continue
        title = str(entry.get("title") or "")
        summary = str(entry.get("summary") or entry.get("description") or "")
        link = str(entry.get("link") or "")
        text_all = f"{title} {summary}"
        tickers = match_industries(text_all)
        if not tickers:
            continue
        matched += 1
        for ticker in tickers:
            row_id = await upsert_signal(
                ticker=ticker,
                source=source,
                signal_type="press_release",
                intensity=0.5,
                payload={"title": title[:200], "url": link},
                detected_at=pub or datetime.now(tz=timezone.utc),
            )
            if row_id is not None:
                inserted += 1
    return {"fetched": len(entries), "matched": matched, "inserted": inserted, "error": 0}


async def poll_gov_press() -> dict[str, Any]:
    sources = _resolve_sources()
    if not sources:
        return {"error": "no_sources"}

    start = datetime.now(tz=timezone.utc)
    cutoff = start - timedelta(hours=_LOOKBACK_HOURS)

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        tasks = [_process(client, s, u, cutoff) for s, u in sources.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    per_source: dict[str, dict[str, int]] = {}
    total_inserted = 0
    for (source, _), result in zip(sources.items(), results):
        if isinstance(result, Exception):
            per_source[source] = {"error": 1}
            continue
        per_source[source] = result
        total_inserted += result.get("inserted", 0)

    stats = {
        "per_source": per_source,
        "total_inserted": total_inserted,
        "elapsed_sec": round((datetime.now(tz=timezone.utc) - start).total_seconds(), 2),
    }
    logger.info("[gov_press] %s", stats)
    return stats
