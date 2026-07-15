"""Ticker Matcher · 종목명 → ticker 매칭 · Sprint 2 T54.

전략:
- KOSDAQ 유니버스 (live_tape_universe · Sniper 필터 통과분) + KOSPI 상위 200
- 정확 substring 매칭 (v1 · 축약·alias skip)
- 이름 길이 내림차순 매칭 순서 (긴 이름 우선 · "삼성전자" > "삼성")
- in-memory cache · 1시간 refresh
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import LiveTapeUniverse

logger = logging.getLogger(__name__)


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
        try:
            entries.extend(await _load_kospi_top(200))
        except Exception as exc:  # noqa: BLE001
            logger.warning("KOSPI 로드 실패 · KOSDAQ 만 사용 · %s", exc)

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
