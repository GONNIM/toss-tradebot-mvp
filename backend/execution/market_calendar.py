"""Market Calendar 게이팅 — v2 트랙 C Phase 2.

Toss GET /api/v1/market-calendar/{KR|US} 응답 기반 정규장/Pre/After 판정.

실측 스키마 (2026-07-10):
    KR: today.integrated.{preMarket, regularMarket, afterMarket} .startTime/endTime
    US: today.{dayMarket, preMarket, regularMarket, afterMarket} .startTime/endTime
    모든 시각은 ISO8601 with tz (KST +09:00 · 서머타임 자동 반영)

스펙: docs/plans/tradebot-mvp-v2/{02-omi-interface-spec.md §5-2, 03-toss-openapi-integration.md}
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .brokers.toss_client import TossClient, get_toss_client
from .models import MarketState

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 30 * 60  # 30분


@dataclass(frozen=True)
class MarketWindows:
    market: str                              # "KR" | "US"
    pre_market: Optional[tuple[datetime, datetime]] = None
    regular_market: Optional[tuple[datetime, datetime]] = None
    after_market: Optional[tuple[datetime, datetime]] = None

    def state(self, now: Optional[datetime] = None) -> MarketState:
        now = now or datetime.now(tz=timezone.utc)
        if self.regular_market and self.regular_market[0] <= now < self.regular_market[1]:
            return MarketState.REGULAR
        if self.pre_market and self.pre_market[0] <= now < self.pre_market[1]:
            return MarketState.PRE_MARKET
        if self.after_market and self.after_market[0] <= now < self.after_market[1]:
            return MarketState.AFTER_HOURS
        return MarketState.CLOSED


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        logger.debug("ISO 파싱 실패 · %s · %s", raw, exc)
        return None


def _window(node: Optional[dict]) -> Optional[tuple[datetime, datetime]]:
    if not isinstance(node, dict):
        return None
    s = _parse_iso(node.get("startTime"))
    e = _parse_iso(node.get("endTime"))
    if s and e:
        return (s, e)
    return None


def _parse_kr(result: dict) -> MarketWindows:
    today = (result.get("today") or {}).get("integrated", {}) or {}
    return MarketWindows(
        market="KR",
        pre_market=_window(today.get("preMarket")),
        regular_market=_window(today.get("regularMarket")),
        after_market=_window(today.get("afterMarket")),
    )


def _parse_us(result: dict) -> MarketWindows:
    today = result.get("today") or {}
    return MarketWindows(
        market="US",
        pre_market=_window(today.get("preMarket")),
        regular_market=_window(today.get("regularMarket")),
        after_market=_window(today.get("afterMarket")),
    )


class MarketCalendar:
    """토스 API 마켓 캘린더 · 30분 캐시 · thread-safe."""

    def __init__(self, toss_client: Optional[TossClient] = None):
        self._toss = toss_client or get_toss_client()
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, MarketWindows]] = {}

    def _fetch(self, market: str) -> MarketWindows:
        env = self._toss.market_calendar(market)
        result = env.result if isinstance(env.result, dict) else {}
        if market.upper() == "KR":
            return _parse_kr(result)
        return _parse_us(result)

    def windows(self, market: str) -> MarketWindows:
        key = market.upper()
        with self._lock:
            entry = self._cache.get(key)
            now = time.time()
            if entry and now - entry[0] < _CACHE_TTL_SEC:
                return entry[1]
        # 캐시 밖 · 잠금 해제 후 fetch (다중 fetch 방지 위해 재확인)
        try:
            fresh = self._fetch(market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("market-calendar fetch 실패 · %s · %s", market, exc)
            # stale 캐시라도 반환 (fail open 방지)
            with self._lock:
                entry = self._cache.get(key)
                if entry:
                    return entry[1]
            # 캐시 자체 없으면 안전 default (CLOSED 로 판정되게 빈 windows)
            return MarketWindows(market=key)
        with self._lock:
            self._cache[key] = (time.time(), fresh)
        return fresh

    def state_for(self, ticker: str) -> MarketState:
        """티커 → 시장 → 현재 상태."""
        market = "KR" if ticker.isdigit() and len(ticker) == 6 else "US"
        return self.windows(market).state()

    def is_regular_hours(self, ticker: str) -> bool:
        return self.state_for(ticker) == MarketState.REGULAR


_calendar: Optional[MarketCalendar] = None


def get_market_calendar() -> MarketCalendar:
    global _calendar
    if _calendar is None:
        _calendar = MarketCalendar()
    return _calendar
