"""RSS 뉴스 피드 클라이언트 — PR/뉴스 카탈리스트.

- PRNewswire 공식 피드 (전체·건강·금융 · 1023-07 · 403 피드는 뺐음)
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

    ticker: Optional[str]   # cashtag 발견 시 채워짐 (첫 표기)
    title: str
    summary: str
    link: str
    published: str          # ISO8601
    source: str             # DEFAULT_FEEDS 키 (예: "PRNewswire (All)")
    tickers: tuple[str, ...] = ()  # 명시 표기 전부 (1027-04 · 한 보도자료에 회사가 여럿)


# 무료 RSS 피드 (회사 발표 위주)
# 2026-10-27 · 1023-07: GlobeNewswire 2곳 · BusinessWire (HTML 포털 주소) 는 403 (AkamaiGHost · 원인 미확인 · 우회 안 함) → 빼고
# PRNewswire 공식 피드 전체·건강을 더함. 피드끼리 같은 보도자료가 겹쳐 fetch_recent 가 link 로 중복을 지운다.
DEFAULT_FEEDS = {
    "PRNewswire (All)": "https://www.prnewswire.com/rss/news-releases-list.rss",
    "PRNewswire (Health)": "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss",
    "PRNewswire (Financial)": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
}

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
# 1027-04 · 거래소 이름은 대소문자 무시 (「(Nasdaq: X)」) · 티커는 대문자만
PAREN_TICKER_RE = re.compile(r"\(\s*(?i:NASDAQ|NYSE|AMEX|OTC)\s*:\s*([A-Z]{1,6})\s*\)")


_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1 Safari/537 TossTradebot/1.0"
# 피드당 4초 × 3개 = 12초 < 호출 측 wait_for 20초 (crazy_picks PER_STEP_TIMEOUT)
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
        # 1028-01 · 피드를 실제로 받을 때만 info (잡마다 피드별 1번 · 잠금 안에서 불림)
        logger.info(f"[RSS] {source_name} fetched {len(parsed.entries)} entries")
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
        seen: set[str] = set()  # 피드끼리 겹친 보도자료는 한 번만 (1023-07)

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
                key = link or entry.get("id", "") or title
                if key in seen:
                    continue
                seen.add(key)

                # ticker 추출 시도
                text = title + " " + summary
                tickers = self._extract_tickers(text)

                items.append(
                    NewsItem(
                        ticker=tickers[0] if tickers else None,
                        title=title,
                        summary=summary[:500],
                        link=link,
                        published=pub_iso,
                        source=source_name,
                        tickers=tickers,
                    )
                )

        # 1028-01 · 캐시 재해석은 종목마다 불려 debug (실제 받기 줄은 _fetch_entries)
        logger.debug(f"[RSS] collected {len(items)} items from {len(self.feeds)} feeds")
        return items

    @staticmethod
    def _extract_tickers(text: str) -> tuple[str, ...]:
        """제목/본문의 명시 표기 전부. cashtag 또는 (NASDAQ:XXX) 형식 · 나온 순서 · 중복 제거."""
        found = [m.group(1).upper() for m in CASHTAG_RE.finditer(text)]
        found += [m.group(1).upper() for m in PAREN_TICKER_RE.finditer(text)]
        return tuple(dict.fromkeys(found))

    def fetch_for_ticker(
        self,
        ticker: str,
        within_hours: int = 48,
    ) -> list[NewsItem]:
        """특정 ticker 를 명시 표기한 아이템만 필터.

        1027-04 (사용자 A 승인 · WP92): 단어 경계 매치는 뺐다 — 「S.A. de C.V.」 의 V,
        「BREA, Calif.」 같은 낱말이 뉴스 건수·LLM 제목으로 들어갔다. 표기 없는 기사는 놓친다.
        """
        all_items = self.fetch_recent(within_hours=within_hours)
        ticker_upper = ticker.upper()
        return [item for item in all_items if ticker_upper in item.tickers]
