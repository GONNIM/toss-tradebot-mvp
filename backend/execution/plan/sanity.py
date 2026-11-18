"""다리별 sanity · 계획서 7-6.

매수 · 사다리 · 비상 손절: 감시가가 직전가 ±40% 안 / TP1: 매수가 초과 · 매수가 × 4 이하 /
추적: 감시가 ≤ 현재가 − 1틱(아니면 7-3 익절 뒤 대기) / 위반이면 등록 거부 + 알림.
각 함수는 위반 사유 문장을 돌려주고 통과면 None.
직전가는 등록 · 수정 순간 6-1 이 읽은 현재가다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .pricing import D, below_by_tick

BAND = Decimal("0.40")
TP1_MAX_MULT = Decimal("4")


def check_band(watch, ref, what: str = "감시가") -> Optional[str]:
    """감시가가 직전가 ±40% 안인가 (매수 · 사다리 · 비상 손절)."""
    w, r = D(watch), D(ref)
    if r <= 0:
        return f"{what} 점검 불가 · 직전가 없음"
    if abs(w - r) / r > BAND:
        return f"{what}가 직전가 ±40% 밖입니다"
    return None


def check_tp1(watch, buy_price) -> Optional[str]:
    """TP1: 매수가 초과 · 매수가 × 4 이하."""
    w, b = D(watch), D(buy_price)
    if b <= 0:
        return "TP1 점검 불가 · 매수가 없음"
    if w <= b:
        return "TP1 감시가가 매수가 이하입니다"
    if w > b * TP1_MAX_MULT:
        return "TP1 감시가가 매수가의 4배를 넘습니다"
    return None


def check_trail(watch, cur) -> Optional[str]:
    """추적: 감시가 ≤ 현재가 − 1틱 (아니면 익절 뒤 대기)."""
    if not below_by_tick(watch, cur):
        return "추적 감시가가 현재가 − 1틱보다 높습니다 · 익절 뒤 대기"
    return None
