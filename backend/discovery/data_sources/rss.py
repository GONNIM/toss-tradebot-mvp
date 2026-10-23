"""RSS 뉴스 피드 클라이언트 — PR/뉴스 카탈리스트.

- PRNewswire, GlobeNewswire, BiopharmaWatch 등 무료 RSS
- 학술 검증 (moonshot-factor-research.md §1.1):
  - PEAD: 단순 PR 노출만으로 알파 약함, 어닝 surprise 결합 필수
- F2 (catalyst 30%) 인자 입력의 일부 — 임박 이벤트·신제품·M&A 등

설계:
- feedparser 사용 (RSS/Atom 표준 라이브러리)
- 다중 피드 병합 + ticker mention 필터
- 24~48h 윈도우
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsItem:
    """RSS 뉴스 단일 항목."""

    ticker: Optional[str]   # cashtag 발견 시 채워짐
    title: str
    summary: str
    link: str
    published: str          # ISO8601
    source: str             # PRNewswire / GlobeNewswire / etc.


# 무료 RSS 피드 (회사 발표 위주)
DEFAULT_FEEDS = {
    "PRNewswire (Financial)": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    "GlobeNewswire (Public Co)": "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20Public%20Companies",
    "GlobeNewswire (Health)": "https://www.globenewswire.com/RssFeed/subjectcode/1-Press-Releases/feedTitle/GlobeNewswire%20-%20All%20Press%20Releases",
    "BusinessWire (Biotech)": "https://www.businesswire.com/portal/site/home/news/industries/?vnsId=31376",
}

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
PAREN_TICKER_RE = re.compile(r"\(\s*(?:NASDAQ|NYSE|AMEX|OTC)\s*:\s*([A-Z]{1,6})\s*\)")


_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1 Safari/537 TossTradebot/1.0"
# 피드당 4초 × 4개 = 16초 < 호출 측 wait_for 20초 (crazy_picks PER_STEP_TIMEOUT)
FEED_TIMEOUT_SEC = 4.0


class RSSClient:
    """RSS 뉴스 피드 통합 클라이언트.

    feedparser는 sync — Phase D 에서 asyncio.to_thread 로 감쌈.

    피드는 httpx 로 시간 제한을 두고 받은 뒤 feedparser 로 해석한다 (2026-10-23 · 1023-01).
    `feedparser.parse(url)` 는 시간 제한이 없어 멈춘 연결이 asyncio 기본 스레드를 붙잡고,
    같은 프로세스의 DNS 조회까지 막아 cron 의 모든 외부 연결·알림이 실패했다.
    피드 원문은 인스턴스(잡 1회) 동안 캐시 — 종목마다 다시 받지 않는다 (실패도 빈 목록으로 캐시).
    """

    def __init__(self, feeds: Optional[dict[str, str]] = None) -> None:
        self.feeds = feeds or DEFAULT_FEEDS
        self._entries_cache: dict[str, list] = {}
        self._cache_lock = threading.Lock()

    def _fetch_entries(self, source_name: str, url: str) -> list:
        """피드 1개 → feedparser 항목 목록. 실패하면 빈 목록."""
        import feedparser

        try:
            resp = httpx.get(
                url, timeout=FEED_TIMEOUT_SEC, follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
            if resp.status_code != 200:
                logger.warning(f"[RSS] {source_name} HTTP {resp.status_code}")
                return []
            parsed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"[RSS] {source_name} fetch failed: {e.__class__.__name__}: {e}")
            return []
        return list(parsed.entries)

    def _cached_entries(self) -> dict[str, list]:
        """모든 피드 항목 (처음 한 번만 받음 · 동시 호출은 잠금으로 기다림)."""
        with self._cache_lock:
            for source_name, url in self.feeds.items():
                if source_name not in self._entries_cache:
                    self._entries_cache[source_name] = self._fetch_entries(source_name, url)
            return dict(self._entries_cache)

    def fetch_recent(
        self,
        within_hours: int = 24,
        max_items_per_feed: int = 100,
    ) -> list[NewsItem]:
        """모든 피드에서 최근 N시간 아이템 수집.

        Note: feedparser 미설치 시 즉시 fallback (빈 리스트).
        """
        try:
            import feedparser  # noqa: F401
        except ImportError:
            logger.warning("feedparser 미설치 — RSS 사용 불가. `pip install feedparser`")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
        items: list[NewsItem] = []

        for source_name, entries in self._cached_entries().items():
            for entry in entries[:max_items_per_feed]:
                # published 파싱
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    pub_iso = pub_dt.isoformat()
                else:
                    pub_iso = ""

                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")

                # ticker 추출 시도
                text = title + " " + summary
                ticker = self._extract_ticker(text)

                items.append(
                    NewsItem(
                        ticker=ticker,
                        title=title,
                        summary=summary[:500],
                        link=link,
                        published=pub_iso,
                        source=source_name,
                    )
                )

        logger.info(f"[RSS] collected {len(items)} items from {len(self.feeds)} feeds")
        return items

    @staticmethod
    def _extract_ticker(text: str) -> Optional[str]:
        """제목/본문에서 ticker 추출. cashtag 또는 (NASDAQ:XXX) 형식."""
        m = CASHTAG_RE.search(text)
        if m:
            return m.group(1).upper()
        m = PAREN_TICKER_RE.search(text)
        if m:
            return m.group(1).upper()
        return None

    def fetch_for_ticker(
        self,
        ticker: str,
        within_hours: int = 48,
    ) -> list[NewsItem]:
        """특정 ticker 멘션 아이템만 필터."""
        all_items = self.fetch_recent(within_hours=within_hours)
        ticker_upper = ticker.upper()
        # ticker 명시 OR title/summary 에 단어 경계로 매치
        word_re = re.compile(rf"\b{re.escape(ticker_upper)}\b")
        return [
            item for item in all_items
            if item.ticker == ticker_upper or word_re.search(item.title + " " + item.summary)
        ]
