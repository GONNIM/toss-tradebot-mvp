"""매수가 기반 이벤트 판정.

이벤트:
    TP1              — 현재가 ≥ 매수가 × (1 + tp1_pct)
    TP2              — 현재가 ≥ 매수가 × (1 + tp2_pct)
    STOP_APPROACH    — 현재가 ≤ 매수가 × (1 + stop_pct)   (stop_pct 음수)
    TRAIL_ARMED      — 최초 pnl ≥ trail_arm_pct 도달 시 armed
    TRAIL_GIVEBACK   — armed 이후 peak - 현재 pnl ≥ trail_giveback_pct

VIP-agnostic (특정 종목 종속 없음). 종목이 바뀌어도 그대로 사용.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .config import VipConfig
from .state import VipState


@dataclass(frozen=True)
class Event:
    name: str
    pnl: float
    current_price: float


def compute_pnl(current_price: float, avg_price: float) -> float:
    if avg_price <= 0.0:
        return 0.0
    return (current_price - avg_price) / avg_price


def evaluate(current_price: float, cfg: VipConfig, state: VipState) -> List[Event]:
    """현재가·설정·상태 → 발송 후보 이벤트 리스트. cooldown 판정은 호출자 몫."""
    events: List[Event] = []
    pnl = compute_pnl(current_price, cfg.avg_price)

    if pnl >= cfg.tp1_pct:
        events.append(Event("TP1", pnl, current_price))
    if pnl >= cfg.tp2_pct:
        events.append(Event("TP2", pnl, current_price))
    if pnl <= cfg.stop_pct:
        events.append(Event("STOP_APPROACH", pnl, current_price))

    if state.trail_armed_at is None and pnl >= cfg.trail_arm_pct:
        state.arm_trail(pnl)
        events.append(Event("TRAIL_ARMED", pnl, current_price))
    else:
        state.update_peak(pnl)

    if (
        state.trail_armed_at is not None
        and state.trail_peak_pnl is not None
        and (state.trail_peak_pnl - pnl) >= cfg.trail_giveback_pct
    ):
        events.append(Event("TRAIL_GIVEBACK", pnl, current_price))

    return events
