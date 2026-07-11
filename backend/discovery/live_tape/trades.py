"""Toss trades 폴러 · Sprint 1 T40.

20초 주기 GET /api/v1/trades?symbol=... 폴링.
개별 체결(tick) 배열 → 최근 체결 통계 산출:
  · trade_count: 응답 배열 크기 (Toss trades API 는 최근 체결만 반환)
  · avg_volume: 평균 체결 volume (주)
  · total_amount_krw: price×volume 총액
  · large_tick_count: 5천만원 이상 개별 tick 수
  · time_span_sec: 첫~마지막 tick 사이 시간

계획서: docs/plans/sniper/00-sprint1-plan.md §2-2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.execution.brokers.toss_client import TossClient, get_toss_client

logger = logging.getLogger(__name__)

_LARGE_TICK_KRW = 50_000_000.0     # 5천만원 이상 = 대량 tick


@dataclass(frozen=True)
class TradesSnapshot:
    ticker: str
    trade_count: int
    avg_volume: float
    total_amount_krw: float
    large_tick_count: int
    intensity: float           # trade_count / time_span_sec (초당 체결 건수)
    time_span_sec: float
    captured_at: datetime
    last_price: Optional[float]


async def poll_trades(ticker: str, toss_client: Optional[TossClient] = None) -> Optional[TradesSnapshot]:
    """단일 종목 체결 스냅샷.

    Returns:
        TradesSnapshot or None (오류·빈 응답)
    """
    client = toss_client or get_toss_client()
    now = datetime.now(tz=timezone.utc)
    try:
        env = client.recent_trades(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trades poll 실패 · %s · %s", ticker, exc)
        return None

    ticks = env.result if isinstance(env.result, list) else []
    if not ticks:
        return None

    trade_count = len(ticks)
    volumes = [float(t.get("volume", 0) or 0) for t in ticks]
    prices = [float(t.get("price", 0) or 0) for t in ticks]
    amounts = [v * p for v, p in zip(volumes, prices)]
    total_amount = sum(amounts)
    large_ticks = sum(1 for a in amounts if a >= _LARGE_TICK_KRW)

    # 시간 스팬 (첫 tick ~ 마지막 tick)
    first_ts = _parse_ts(ticks[-1].get("timestamp"))
    last_ts = _parse_ts(ticks[0].get("timestamp"))
    if first_ts and last_ts:
        span = max(1.0, (last_ts - first_ts).total_seconds())
    else:
        span = 1.0

    intensity = trade_count / span
    last_price = prices[0] if prices else None
    avg_volume = sum(volumes) / trade_count if trade_count else 0.0

    return TradesSnapshot(
        ticker=ticker,
        trade_count=trade_count,
        avg_volume=avg_volume,
        total_amount_krw=total_amount,
        large_tick_count=large_ticks,
        intensity=intensity,
        time_span_sec=span,
        captured_at=now,
        last_price=last_price,
    )


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
