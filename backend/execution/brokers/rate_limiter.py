"""Toss API Rate Limit — 그룹별 leaky bucket + 피크 스로틀 + 429 재시도.

스펙: docs/plans/tradebot-mvp-v2/03-toss-openapi-integration.md §6
     메모리 reference_toss_open_api Rate Limits

원칙:
- 그룹별 한도 이내 자동 스로틀 (안전 상한 20~30%)
- 09:00~09:10 KST → ORDER · ORDER_INFO 를 6/s → 3/s 로 자동 다운
- 429 응답 시 Retry-After 우선 · 없으면 지수 백오프 1s → 2s → 4s + jitter (3회)
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class GroupLimit:
    name: str
    limit_per_sec: float          # 안전 상한 (Toss 문서 상한의 60~80%)
    peak_limit_per_sec: Optional[float] = None  # 09:00~09:10 KST 강제 하향치


# 안전 상한 (Toss 상한 대비 여유 20~30%)
_GROUPS: dict[str, GroupLimit] = {
    "AUTH": GroupLimit("AUTH", 1.0),                           # Toss 5/s → 1/s (토큰 캐시)
    "ACCOUNT": GroupLimit("ACCOUNT", 0.5),                     # Toss 1/s → 0.5/s
    "ASSET": GroupLimit("ASSET", 3.0),                         # Toss 5/s → 3/s
    "STOCK": GroupLimit("STOCK", 3.0),
    "MARKET_INFO": GroupLimit("MARKET_INFO", 2.0),
    "MARKET_DATA": GroupLimit("MARKET_DATA", 8.0),             # Toss 10/s → 8/s
    "MARKET_DATA_CHART": GroupLimit("MARKET_DATA_CHART", 3.0), # Toss 5/s → 3/s
    "RANKING": GroupLimit("RANKING", 3.0),
    "MARKET_INDICATOR_PRICE": GroupLimit("MARKET_INDICATOR_PRICE", 8.0),
    "MARKET_INDICATOR": GroupLimit("MARKET_INDICATOR", 8.0),
    "MARKET_INDICATOR_CHART": GroupLimit("MARKET_INDICATOR_CHART", 3.0),
    "ORDER": GroupLimit("ORDER", 4.0, peak_limit_per_sec=2.0),      # Toss 6/s (피크 3/s)
    "ORDER_HISTORY": GroupLimit("ORDER_HISTORY", 3.0),
    "ORDER_INFO": GroupLimit("ORDER_INFO", 4.0, peak_limit_per_sec=2.0),
    "CONDITIONAL_ORDER": GroupLimit("CONDITIONAL_ORDER", 3.0),
    "CONDITIONAL_ORDER_HISTORY": GroupLimit("CONDITIONAL_ORDER_HISTORY", 8.0),
}


# 경로 프리픽스 → 그룹
_PATH_GROUP_MAP: list[tuple[str, str]] = [
    ("/oauth2/token", "AUTH"),
    ("/api/v1/accounts", "ACCOUNT"),
    ("/api/v1/holdings", "ASSET"),
    ("/api/v1/buying-power", "ORDER_INFO"),
    ("/api/v1/sellable-quantity", "ORDER_INFO"),
    ("/api/v1/commissions", "ORDER_INFO"),
    ("/api/v1/orders", "ORDER"),
    ("/api/v1/conditional-orders", "CONDITIONAL_ORDER"),
    ("/api/v1/prices", "MARKET_DATA"),
    ("/api/v1/orderbook", "MARKET_DATA"),
    ("/api/v1/trades", "MARKET_DATA"),
    ("/api/v1/price-limits", "MARKET_DATA"),
    ("/api/v1/candles", "MARKET_DATA_CHART"),
    ("/api/v1/stocks", "STOCK"),
    ("/api/v1/exchange-rate", "MARKET_INFO"),
    ("/api/v1/market-calendar", "MARKET_INFO"),
    ("/api/v1/rankings", "RANKING"),
    ("/api/v1/market-indicators", "MARKET_INDICATOR"),
]


def resolve_group(path: str) -> str:
    for prefix, group in _PATH_GROUP_MAP:
        if path.startswith(prefix):
            return group
    return "MARKET_INFO"  # 기본 (보수적)


def is_peak_time(now: Optional[datetime] = None) -> bool:
    """09:00~09:10 KST 개장 직후 피크."""
    now = (now or datetime.now(tz=_KST)).astimezone(_KST)
    t = now.time()
    return dtime(9, 0) <= t < dtime(9, 10)


class LeakyBucket:
    """단순 leaky bucket · 초당 한도 이내 강제 스로틀."""

    def __init__(self, limit_per_sec: float):
        self._limit = float(limit_per_sec)
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 5.0) -> None:
        """토큰 대기. 없으면 sleep 후 다시 시도."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                # 1초 이전 이벤트 제거
                while self._events and now - self._events[0] > 1.0:
                    self._events.popleft()
                if len(self._events) < self._limit:
                    self._events.append(now)
                    return
                oldest = self._events[0]
            sleep_for = max(0.02, 1.0 - (time.monotonic() - oldest))
            if time.monotonic() + sleep_for > deadline:
                logger.warning("leaky bucket timeout · %s", self._limit)
                # timeout 이지만 클라 측 blocking 회피 · 그냥 진입
                with self._lock:
                    self._events.append(time.monotonic())
                return
            time.sleep(sleep_for)


class RateLimiter:
    """그룹별 LeakyBucket 관리 · 피크 시간 동적 스로틀."""

    def __init__(self):
        self._buckets_normal: dict[str, LeakyBucket] = {}
        self._buckets_peak: dict[str, LeakyBucket] = {}
        for name, spec in _GROUPS.items():
            self._buckets_normal[name] = LeakyBucket(spec.limit_per_sec)
            if spec.peak_limit_per_sec is not None:
                self._buckets_peak[name] = LeakyBucket(spec.peak_limit_per_sec)

    def acquire(self, path: str) -> str:
        group = resolve_group(path)
        if is_peak_time() and group in self._buckets_peak:
            self._buckets_peak[group].acquire()
            logger.debug("rate acquire (PEAK) · %s · %s", group, path)
        else:
            bucket = self._buckets_normal.get(group)
            if bucket is not None:
                bucket.acquire()
            logger.debug("rate acquire · %s · %s", group, path)
        return group


def retry_with_backoff(
    fn: Callable[[], object],
    *,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
) -> object:
    """429 · 일시적 5xx 재시도 헬퍼. Retry-After 준수 · 지수 백오프 + jitter."""
    from ..exceptions import BrokerCommunicationError, RateLimitExceeded

    delay = initial_delay
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except RateLimitExceeded as exc:
            last_exc = exc
            wait = exc.retry_after if exc.retry_after else delay
            jitter = random.uniform(0, 0.3)
            logger.warning(
                "429 · Retry-After=%s · 대기 %.2fs · attempt=%d/%d",
                exc.retry_after, wait + jitter, attempt, max_attempts,
            )
            if attempt >= max_attempts:
                break
            time.sleep(wait + jitter)
            delay = min(delay * 2, 16.0)
        except BrokerCommunicationError as exc:
            last_exc = exc
            jitter = random.uniform(0, 0.3)
            logger.warning(
                "5xx/네트워크 · 대기 %.2fs · attempt=%d/%d · %s",
                delay + jitter, attempt, max_attempts, exc,
            )
            if attempt >= max_attempts:
                break
            time.sleep(delay + jitter)
            delay = min(delay * 2, 16.0)
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_with_backoff 도달 불가")


# 프로세스 lifetime 싱글턴
_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
