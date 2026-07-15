"""Watchlist Paper 시뮬 러너 · Sprint 2 Week 4 T68.

목적: 실 5거래일 forward test 프레임워크. 데이터 축적 전에도 시나리오 기반 검증 가능.

입력:
    scenarios: list[DayScenario] · 각 거래일 · Watchlist + 종목별 (prev_close, open, intraday_high, close)

출력: list[Trade] · 진입 판정 → 체결 시뮬 → 청산 시나리오 반영

시뮬 규칙 (v1):
  · 진입: watchlist_gap_min <= (open - prev_close) / prev_close <= watchlist_gap_max
        AND composite_score >= watchlist_min_composite_score
  · 청산: 다음 중 하나 · 시간 우선순위
      1. intraday_high >= entry × (1 + trailing_giveback_target) · trailing 목표 매도
      2. close 종가 시점 · 미청산 시 · force_close (15:00)
      3. 손절 · intraday_low <= entry × (1 - hard_stop_loss)

계획서: docs/plans/sniper/02-strategic-pivot-as-is-to-be.md §3 Week 4
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from backend.discovery.live_tape.params import SniperParams

from .metrics import Trade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimTickerBar:
    """일봉 데이터 · 시뮬 입력."""
    ticker: str
    composite_score: float
    prev_close: float
    open_price: float
    intraday_high: float
    intraday_low: float
    close_price: float


@dataclass(frozen=True)
class DayScenario:
    """단일 거래일 시나리오."""
    trade_date: str            # YYYY-MM-DD
    bars: list[SimTickerBar]


@dataclass
class SimSummary:
    """시뮬 요약."""
    trades: list[Trade] = field(default_factory=list)
    entries: int = 0
    exits: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    per_day: list[dict] = field(default_factory=list)


def simulate(scenarios: list[DayScenario], params: SniperParams) -> SimSummary:
    """시나리오 리스트 → 매매 시뮬.

    각 거래일 마다:
      1. Watchlist 대상 필터 (composite_score ≥ min · 갭업 범위)
      2. open_price 진입
      3. intraday 청산 판정 (trailing / hard SL / force_close)
    """
    summary = SimSummary()

    for day in scenarios:
        day_stats = {"trade_date": day.trade_date, "entered": 0, "won": 0, "lost": 0}
        for bar in day.bars:
            reject = _check_entry(bar, params)
            if reject:
                summary.rejected[reject] = summary.rejected.get(reject, 0) + 1
                continue

            summary.entries += 1
            day_stats["entered"] += 1

            trade = _simulate_exit(bar, params, day.trade_date)
            summary.trades.append(trade)
            summary.exits += 1
            if trade.pnl_pct > 0:
                day_stats["won"] += 1
            else:
                day_stats["lost"] += 1
        summary.per_day.append(day_stats)

    return summary


def _check_entry(bar: SimTickerBar, params: SniperParams) -> Optional[str]:
    """진입 조건 위반 사유 반환 · None 이면 통과."""
    if bar.composite_score < params.watchlist_min_composite_score:
        return f"below_min_score({bar.composite_score:.2f})"
    if bar.prev_close <= 0:
        return "no_prev_close"
    gap = (bar.open_price - bar.prev_close) / bar.prev_close
    if gap < params.watchlist_gap_min_pct:
        return f"gap_below_min({gap*100:+.2f}%)"
    if gap > params.watchlist_gap_max_pct:
        return f"gap_above_max_상투({gap*100:+.2f}%)"
    return None


def _simulate_exit(bar: SimTickerBar, params: SniperParams, trade_date: str) -> Trade:
    """intraday 청산 판정.

    우선순위:
      1. hard SL (intraday_low ≤ entry × (1 + hard_stop_loss_pct))
      2. trailing target (intraday_high ≥ entry × (1 + trailing_target)) · 목표=3%
      3. close 종가 (force_close_kst)
    """
    entry = bar.open_price
    # v1: trailing target = trailing_giveback_pct (약 3%) · 실제 trailing 로직은 peak 추적 후 giveback
    # 시뮬 단순화: 진입가 대비 목표 상승 = 상승률 (giveback 만큼 되돌리기 전 peak)
    target_up = 1.0 + params.trailing_giveback_pct * 1.5   # 예: 3% × 1.5 = 4.5% 목표
    stop_down = 1.0 + params.hard_stop_loss_pct             # 예: -3%

    hit_stop = bar.intraday_low <= entry * stop_down
    hit_target = bar.intraday_high >= entry * target_up

    if hit_stop and hit_target:
        # 최악 가정: SL 먼저 · 보수적
        exit_price = entry * stop_down
        reason = "hard_sl_before_target"
    elif hit_stop:
        exit_price = entry * stop_down
        reason = "hard_sl"
    elif hit_target:
        # peak - giveback 을 시뮬 · peak = intraday_high · giveback 후 exit
        peak = bar.intraday_high
        exit_price = peak * (1.0 - params.trailing_giveback_pct)
        reason = "trailing_target"
    else:
        exit_price = bar.close_price
        reason = "force_close"

    return Trade(
        ticker=bar.ticker,
        entry_price=entry,
        exit_price=exit_price,
        entry_time=None,
        exit_time=None,
        reason=reason,
    )
