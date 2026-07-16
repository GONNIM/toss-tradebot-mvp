"""뉴스 크롤러 · Phase 7-1-4 · A1/A2/A6 표본 확보.

지시서 §7-1-4 두 번째 항목:
    "뉴스 크롤링(선택): 화약고 리스트 종목명 + {구속, 기소, 검찰, 압수수색, 별세, 상속} 키워드 매칭."

Sprint 2 T54 (news_rss.py) 재사용 · RSS 5 소스 · matcher · 매칭 로직.
차이:
  - Sprint 2: watchlist_signal 저장 (인기/센티멘트)
  - Phase 7 : PowderKegEvent 저장 (A1/A2/A6 · 오너 사법·상속·정책 압박)

A3~A5/B1~B3 는 DART 공시로 이미 커버 (events.py). 뉴스 크롤러는 A1/A2/A6 표본 보완용.

동작:
  1. 5 RSS 소스 병렬 fetch (news_rss.RSS_SOURCES 재사용)
  2. entries 순회 · title+summary 에 A1/A2/A6 keyword 매칭
  3. matcher 로 종목 매칭 · 화약고 리스트에 있는 종목만 저장
  4. PowderKegEvent 삽입 · source="news_rss_<domain>" · source_id="rss:<url>"
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select

from backend.discovery.watchlist.matcher import get_matcher
from backend.discovery.watchlist.news_rss import (
    RSS_SOURCES,
    _USER_AGENT,
    _entry_time,
    _fetch,
    _parse_entries,
)
from backend.services.db import get_session
from backend.services.models import PowderKegEvent, PowderKegList

from ..config import KEYWORDS_TYPE_A

logger = logging.getLogger(__name__)


# Phase 7-1-4 · 뉴스 크롤링 대상은 A1/A2/A6 (DART 공시로 커버 안 되는 항목)
_NEWS_TARGET_TYPES = ("A1_owner_legal_risk", "A2_owner_inheritance", "A6_reform_pressure")


def _classify_news_title(text: str) -> Optional[tuple[str, str]]:
    """뉴스 title+summary → (event_type_full, matched_keyword) · A1/A2/A6 만.

    DART 공시와 별개 · Type B 우선순위 규칙은 뉴스에서 미적용 (뉴스는 신호 · 공식 아님).
    """
    if not text:
        return None
    for etype in _NEWS_TARGET_TYPES:
        keywords = KEYWORDS_TYPE_A.get(etype, ())
        for kw in keywords:
            if kw in text:
                return (etype, kw)
    return None


def _short_code(event_type_full: str) -> str:
    return event_type_full.split("_")[0]


async def _get_watched_tickers() -> Optional[set[str]]:
    """최신 run_id · PowderKegList (passed/cash_suspect) 종목 반환.

    None 반환 시 · 전체 종목 저장 (스팸 위험 · 화약고 리스트 확정 후 권장).
    """
    async with get_session() as session:
        latest_run = (await session.execute(
            select(PowderKegList.run_id)
            .order_by(PowderKegList.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if latest_run is None:
            return set()
        rows = (await session.execute(
            select(PowderKegList.ticker).where(PowderKegList.run_id == latest_run)
        )).scalars().all()
    return set(rows)


async def _already_saved(source: str, source_id: str) -> bool:
    async with get_session() as session:
        stmt = select(PowderKegEvent.id).where(
            PowderKegEvent.source == source,
            PowderKegEvent.source_id == source_id,
        ).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _save_news_event(
    ticker: str,
    event_type_full: str,
    matched_kw: str,
    title: str,
    url: str,
    published: Optional[datetime],
    source: str,
) -> Optional[int]:
    # source_id = 뉴스 url 해시 (rcept_no 없음)
    src_id = f"rss:{hashlib.md5(url.encode('utf-8')).hexdigest()[:16]}"
    if await _already_saved(source, src_id):
        return None
    async with get_session() as session:
        row = PowderKegEvent(
            ticker=ticker,
            event_type=_short_code(event_type_full),
            source=source,
            source_id=src_id,
            title=title[:500],
            url=url[:500],
            release_date=published or datetime.now(tz=timezone.utc),
        )
        session.add(row)
        await session.flush()
        return row.id


async def poll_powderkeg_news(
    lookback_hours: int = 24,
    only_watched: bool = True,
) -> dict[str, Any]:
    """5 RSS 소스 병렬 fetch · A1/A2/A6 매칭 · PowderKegEvent 저장.

    Args:
        lookback_hours: 최근 N 시간 이내 뉴스만 저장 (기본 24 · v1 안전)
        only_watched: True 시 화약고 리스트 종목만 저장 (권장)

    Returns:
        {"per_source": {...}, "matched": M, "inserted": I, "by_type": {A1: n, A2: m, ...}}
    """
    matcher = get_matcher()
    await matcher.ensure_loaded()
    if matcher.size() == 0:
        return {"error": "empty_matcher", "matcher_size": 0}

    watched: Optional[set[str]] = None
    if only_watched:
        watched = await _get_watched_tickers()
        if not watched:
            return {"info": "empty_powderkeg_list · run screener first", "matched": 0, "inserted": 0}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    stats: dict[str, Any] = {
        "per_source": {}, "matched": 0, "inserted": 0,
        "by_type": {"A1": 0, "A2": 0, "A6": 0},
    }

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        for src, url in RSS_SOURCES.items():
            xml = await _fetch(client, src, url)
            if xml is None:
                stats["per_source"][src] = {"error": 1}
                continue
            entries = _parse_entries(src, xml)
            s_matched = s_inserted = 0
            for e in entries:
                pub = _entry_time(e)
                if pub is not None and pub < cutoff:
                    continue
                title = str(e.get("title") or "")
                summary = str(e.get("summary") or e.get("description") or "")
                link = str(e.get("link") or "")
                text = f"{title} {summary}"

                cls = _classify_news_title(text)
                if cls is None:
                    continue

                tickers = matcher.match_text(text)
                if not tickers:
                    continue
                event_type_full, kw = cls
                for tk in tickers:
                    if watched is not None and tk not in watched:
                        continue
                    s_matched += 1
                    rid = await _save_news_event(
                        ticker=tk,
                        event_type_full=event_type_full,
                        matched_kw=kw,
                        title=title,
                        url=link,
                        published=pub,
                        source=src,
                    )
                    if rid is not None:
                        s_inserted += 1
                        stats["by_type"][_short_code(event_type_full)] = (
                            stats["by_type"].get(_short_code(event_type_full), 0) + 1
                        )
            stats["per_source"][src] = {
                "entries": len(entries), "matched": s_matched, "inserted": s_inserted,
            }
            stats["matched"] += s_matched
            stats["inserted"] += s_inserted

    logger.info("[powderkeg.news] %s", stats)
    return stats
