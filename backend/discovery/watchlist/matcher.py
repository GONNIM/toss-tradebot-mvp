"""Ticker Matcher · 종목명 → ticker 매칭 · Sprint 2 T54.

전략:
- KOSDAQ 유니버스 (live_tape_universe · Sniper 필터 통과분) + KOSPI 상위 200
- 정확 substring 매칭 (v1 · 축약·alias skip)
- 이름 길이 내림차순 매칭 순서 (긴 이름 우선 · "삼성전자" > "삼성")
- in-memory cache · 1시간 refresh

1030-04:
- match_text 는 그대로 (유튜브·화약고가 씀) · 뉴스는 match_news (오탐 규칙 · 별칭 · 다종목 분산)
- 코스피 적재가 실패하면 직전 코스피 항목을 유지하고, 마지막 성공 목록은 런타임 파일에 남겨 재시작 때 쓴다
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import LiveTapeUniverse

from . import runtime_paths

logger = logging.getLogger(__name__)

_ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "watchlist_aliases.json"
# data/ 가 .gitignore 라 파일이 서버에 없을 수 있다 · 없으면 이 시드를 쓴다 (확실한 것만)
_DEFAULT_ALIASES: dict[str, str] = {
    "삼전": "005930", "하이닉스": "000660", "삼성바이오": "207940", "삼바": "207940",
    "LG엔솔": "373220", "엘지엔솔": "373220", "엘지에너지솔루션": "373220",
    "네이버": "035420", "한전": "015760",
}
_KOSPI_CACHE_FILE = "matcher_kospi.json"

# 뉴스 매칭 가중 (1030-04 · 결정 8 오탐 규칙 = 뉴스만)
# · 한 기사에 4종목 이상이면 시황·종합 기사라 어느 한 종목의 재료가 아니다 → 각 1/n
# · 요약에서만 걸리면 제목에서 걸린 것보다 약하다 → ×0.5
_MANY_TICKERS_MIN = 4
_SUMMARY_ONLY_FACTOR = 0.5
_SHORT_NAME_MAX = 2       # 2글자 이하 이름은 제목에서만 (요약 속 우연한 일치가 많다)
_ALNUM = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class MatcherEntry:
    ticker: str
    name: str
    market: str  # KOSDAQ | KOSPI


class TickerMatcher:
    def __init__(self) -> None:
        self._entries: list[MatcherEntry] = []
        self._name_index: list[tuple[str, str]] = []  # (name_lower, ticker) sorted by name len desc
        self._loaded_at: Optional[datetime] = None
        self._refresh_ttl = timedelta(hours=1)
        self._kospi_entries: list[MatcherEntry] = []   # 마지막으로 성공한 코스피 목록 (적재 실패 때 유지)
        self._aliases: Optional[dict[str, str]] = None
        self._news_cache: Optional[tuple[int, list[tuple[str, str]]]] = None

    async def ensure_loaded(self) -> None:
        if self._loaded_at is None or datetime.now(tz=timezone.utc) - self._loaded_at > self._refresh_ttl:
            await self.reload()

    async def reload(self) -> int:
        entries: list[MatcherEntry] = []

        # KOSDAQ · live_tape_universe
        async with get_session() as session:
            rows = (await session.execute(select(LiveTapeUniverse))).scalars().all()
        for r in rows:
            entries.append(MatcherEntry(ticker=r.ticker, name=r.name, market="KOSDAQ"))

        # KOSPI 상위 200 · FinanceDataReader (best-effort)
        # 실패하면 코스닥만으로 덮지 않고 직전 코스피를 유지한다 (1030-04 · 이름 빈칸·삼성전자 실종 방지)
        try:
            kospi = await _load_kospi_top(200)
            if kospi:
                self._kospi_entries = kospi
                runtime_paths.write_json(_KOSPI_CACHE_FILE, {
                    "saved_at": datetime.now(tz=timezone.utc).isoformat(),
                    "entries": [{"ticker": e.ticker, "name": e.name} for e in kospi],
                })
            elif not self._kospi_entries:
                self._kospi_entries = _read_kospi_cache()
        except Exception as exc:  # noqa: BLE001
            if not self._kospi_entries:
                self._kospi_entries = _read_kospi_cache()
            logger.warning(
                "KOSPI 로드 실패 · 직전 코스피 %d종목 유지 · %s", len(self._kospi_entries), exc,
            )
        entries.extend(self._kospi_entries)

        # dedup by ticker
        seen: set[str] = set()
        uniq: list[MatcherEntry] = []
        for e in entries:
            if e.ticker in seen:
                continue
            seen.add(e.ticker)
            uniq.append(e)

        # 이름 길이 내림차순 정렬 (긴 이름 우선 매칭)
        uniq.sort(key=lambda e: -len(e.name))
        self._entries = uniq
        self._name_index = [(e.name.lower(), e.ticker) for e in uniq if e.name]
        self._loaded_at = datetime.now(tz=timezone.utc)
        logger.info("[matcher] loaded · entries=%d", len(uniq))
        return len(uniq)

    def match_text(self, text: str) -> list[str]:
        """text 에서 매칭된 ticker 리스트 (중복 제거 · 순서 보존)."""
        if not text:
            return []
        low = text.lower()
        hits: list[str] = []
        seen: set[str] = set()
        # 긴 이름부터 매칭 · 매칭 후 해당 substring 제거하여 부분매칭 억제
        remaining = low
        for name, ticker in self._name_index:
            if len(name) < 2:
                continue
            if name in remaining:
                if ticker not in seen:
                    seen.add(ticker)
                    hits.append(ticker)
                remaining = remaining.replace(name, " " * len(name))
        return hits

    # ─── 뉴스 전용 매칭 (1030-04) ─────────────────────
    def _alias_table(self) -> dict[str, str]:
        if self._aliases is None:
            aliases = dict(_DEFAULT_ALIASES)
            try:
                raw = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    aliases.update({str(k): str(v) for k, v in raw.items() if k and v})
            except (OSError, ValueError):
                pass
            self._aliases = aliases
        return self._aliases

    def _news_index(self) -> list[tuple[str, str]]:
        """(이름 소문자, ticker) · 정식 이름 + 별칭 · 긴 것 먼저. 목록이 바뀔 때만 다시 만든다."""
        key = hash((tuple((e.ticker, e.name) for e in self._entries), id(self._aliases)))
        if self._news_cache is None or self._news_cache[0] != key:
            pairs = [(e.name.lower(), e.ticker) for e in self._entries if e.name]
            pairs += [(a.lower(), tk) for a, tk in self._alias_table().items()]
            pairs.sort(key=lambda p: -len(p[0]))
            self._news_cache = (key, pairs)
        return self._news_cache[1]

    def match_news(self, title: str, summary: str = "") -> list[tuple[str, float]]:
        """뉴스 기사 → [(ticker, weight)] (1030-04).

        match_text 와 다른 점:
          · 영문·숫자가 들어간 이름은 앞뒤가 영문·숫자가 아닐 때만 (ELS 안의 LS 금지)
          · 2글자 이하 이름은 제목에서만
          · 별칭표(watchlist_aliases.json) 사용
          · 4종목 이상이면 각 1/n · 요약에서만 걸리면 ×0.5
        """
        index = self._news_index()
        hits: dict[str, bool] = {}   # ticker → 제목에서 걸렸는가
        for text, is_title in ((title or "", True), (summary or "", False)):
            remaining = text.lower()
            for name, ticker in index:
                if len(name) < 2:
                    continue
                if not is_title and len(name) <= _SHORT_NAME_MAX:
                    continue
                spans = _find_spans(remaining, name)
                if not spans:
                    continue
                for start, end in spans:
                    remaining = remaining[:start] + " " * (end - start) + remaining[end:]
                if ticker not in hits or (is_title and not hits[ticker]):
                    hits[ticker] = is_title
        if not hits:
            return []
        crowd = 1.0 / len(hits) if len(hits) >= _MANY_TICKERS_MIN else 1.0
        return [
            (ticker, round(crowd * (1.0 if in_title else _SUMMARY_ONLY_FACTOR), 4))
            for ticker, in_title in hits.items()
        ]

    def size(self) -> int:
        return len(self._entries)

    def entries(self) -> list[MatcherEntry]:
        return list(self._entries)


_singleton: Optional[TickerMatcher] = None


def get_matcher() -> TickerMatcher:
    global _singleton
    if _singleton is None:
        _singleton = TickerMatcher()
    return _singleton


def _find_spans(text: str, name: str) -> list[tuple[int, int]]:
    """name 이 text 에 나오는 자리 · 영문·숫자가 들어간 이름은 앞뒤 글자가 영문·숫자면 건너뛴다."""
    guard = bool(_ALNUM.search(name))
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        i = text.find(name, pos)
        if i < 0:
            return spans
        j = i + len(name)
        pos = j
        if guard:
            if i > 0 and _ALNUM.match(text[i - 1]):
                continue
            if j < len(text) and _ALNUM.match(text[j]):
                continue
        spans.append((i, j))


def _read_kospi_cache() -> list[MatcherEntry]:
    raw = runtime_paths.read_json(_KOSPI_CACHE_FILE)
    entries: list[MatcherEntry] = []
    if isinstance(raw, dict):
        for r in raw.get("entries") or []:
            if isinstance(r, dict) and r.get("ticker") and r.get("name"):
                entries.append(MatcherEntry(ticker=str(r["ticker"]), name=str(r["name"]), market="KOSPI"))
    return entries


async def _load_kospi_top(limit: int) -> list[MatcherEntry]:
    """FinanceDataReader 로 KOSPI 시총 상위 N 종목."""
    import FinanceDataReader as fdr  # noqa: PLC0415

    df = fdr.StockListing("KOSPI")
    if "Marcap" in df.columns:
        df = df.sort_values("Marcap", ascending=False)
    df = df.head(limit)
    result: list[MatcherEntry] = []
    for _, r in df.iterrows():
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not code or not name:
            continue
        result.append(MatcherEntry(ticker=code, name=name, market="KOSPI"))
    return result
