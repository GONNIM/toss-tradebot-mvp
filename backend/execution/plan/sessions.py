"""시간대 다리 값 · 시간 손절 시각 · 고점 규칙 · 계획서 7-1 · 7-3 · 7-4.

- 장 시간은 토스 market-calendar (기존 execution/market_calendar.py) 를 읽은 MarketWindows 로 받는다.
- 정규장 다리: 사다리(기본 −3·−5·−7%) · 주문가 = 감시가 × 0.98.
- 정규장 밖(데이 · 프리 · 애프터): 3건 모두 비상 손절 −15% · 주문가 × 0.97.
- 전환 시각: 정규장 시작 1분 뒤 · 종료 1분 뒤.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from .pricing import D, cap_sell_watch, floor_tick, order_price_from_watch, sell_watch

REGULAR_FACTOR = Decimal("0.98")
OFFHOURS_FACTOR = Decimal("0.97")
EMERGENCY_FACTOR = Decimal("0.85")          # 비상 손절 −15%
DEFAULT_LADDER_PCTS = (Decimal("0.03"), Decimal("0.05"), Decimal("0.07"))
WIDE_LADDER_PCTS = (Decimal("0.045"), Decimal("0.075"), Decimal("0.105"))  # 「제안」으로만 (D7)
SWAP_DELAY = timedelta(minutes=1)


@dataclass(frozen=True)
class Values:
    watch: Decimal
    order: Decimal


def leg_session(now: datetime, regular: Optional[tuple[datetime, datetime]]) -> str:
    """'regular' 은 정규장 시작 1분 뒤 ~ 종료 1분 뒤. 그 밖은 'off'. 정규장 정보가 없으면 'off'(안전측)."""
    if not regular:
        return "off"
    start, end = regular
    return "regular" if start + SWAP_DELAY <= now < end + SWAP_DELAY else "off"


def ladder_values(avg: Decimal | float, pcts=DEFAULT_LADDER_PCTS) -> list[Values]:
    out = []
    for p in pcts:
        w = sell_watch(D(avg) * (1 - D(p)))
        out.append(Values(w, order_price_from_watch(w, REGULAR_FACTOR)))
    return out


def emergency_values(cur: Decimal | float) -> Values:
    w = sell_watch(D(cur) * EMERGENCY_FACTOR)
    return Values(w, order_price_from_watch(w, OFFHOURS_FACTOR))


def trail_values(avg: Decimal | float, peak: Decimal | float) -> Values:
    """추적 감시가 = max(평단, 정규장 고점 × 0.85) · 주문가 × 0.98."""
    w = sell_watch(max(D(avg), D(peak) * EMERGENCY_FACTOR))
    return Values(w, order_price_from_watch(w, REGULAR_FACTOR))


def lift_values(cur: Decimal | float) -> Values:
    """끌어올리기 1단계 = min(현재가 × 0.99 올림, 현재가 − 2틱) · 주문가 = 현재가 × 0.98 내림."""
    w = cap_sell_watch(D(cur) * Decimal("0.99"), cur)
    return Values(w, floor_tick(D(cur) * REGULAR_FACTOR))


def raise_only(new: Values, old_watch: Optional[Decimal | float]) -> Optional[Values]:
    """위로만 올린다 (추적 · 끌어올리기). 올릴 게 없으면 None."""
    if old_watch is not None and new.watch <= D(old_watch):
        return None
    return new


def trail_min_step(old_watch: Decimal | float) -> Decimal:
    """추적 상향 최소 폭 = $0.005 또는 감시가의 0.5% 중 큰 값."""
    return max(Decimal("0.005"), D(old_watch) * Decimal("0.005"))


def trail_should_raise(old_watch: Decimal | float, new_watch: Decimal | float) -> bool:
    return D(new_watch) - D(old_watch) >= trail_min_step(old_watch)


def update_peak(peak: Optional[float], pending: Optional[float], close: float) -> tuple[Optional[float], Optional[float]]:
    """정규장 1분봉 종가로 고점 갱신 (7-3). 직전 고점보다 10% 넘게 높은 값은 다음 1분봉이 3% 안에서 확인할 때까지 보류."""
    if peak is None:
        return close, None
    if pending is not None:
        if abs(close - pending) / pending <= 0.03:
            return max(peak, pending), None
        pending = None
    if close <= peak:
        return peak, None
    if close > peak * 1.10:
        return peak, close
    return close, None


# ─── 시간 손절 (7-4) ───────────────────────────────────────────

def add_trading_days(start: date, n: int, holidays: frozenset[date] = frozenset()) -> date:
    """start 다음 거래일부터 n 번째 거래일. 주말 + 받은 휴장일을 건너뛴다."""
    d, k = start, 0
    while k < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            k += 1
    return d


def timestop_due(announce_at: datetime, now: datetime, holidays: frozenset[date] = frozenset()) -> bool:
    """발표 시각 + 5거래일이 지났는가. (그 뒤 다음 정규장 시작 30분 뒤부터 시작은 실행기가 시각으로 맞춘다.)"""
    return now.date() > add_trading_days(announce_at.date(), 5, holidays)


@dataclass(frozen=True)
class TimestopWindow:
    lift_from: datetime        # 정규장 시작 30분 뒤
    clean_from: datetime       # 종료 30분 전 (정리 시작)
    cancel_at: datetime        # 종료 1분 전 (미체결 매도 취소)


def timestop_window(regular: tuple[datetime, datetime]) -> TimestopWindow:
    s, e = regular
    return TimestopWindow(s + timedelta(minutes=30), e - timedelta(minutes=30), e - timedelta(minutes=1))
