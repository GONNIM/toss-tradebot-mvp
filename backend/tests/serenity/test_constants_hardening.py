"""Serenity Hunter · 상수 하한 방어 (Phase L14 · Fable 5 5차 옆문 마찰).

폐기식 (constants.COST_ROUND_TRIP_PCT · SLIPPAGE_PCT) 을 조용히 낮추는 우회 방지.
낮추려면 이 테스트의 MIN_* 상수도 함께 수정 필요 → git diff 노출 강제.

Fable 5 5차 지적 원문 요약:
    "constants.py 의 COST_ROUND_TRIP_PCT 나 SLIPPAGE_PCT 를 낮추면 폐기식이 발동하지 않게
    되는데, 이 변경은 티켓도 §11 기록도 요구하지 않음. OVERRIDE 에 마찰을 걸어놓고
    옆문은 무장금인 셈."

방어 원리 (Fable 5 5차 승인):
    - assert 로 하한 강제 · 하향 시 test fail
    - 실측치가 하한 이하로 확인되어 정당한 하향이 필요하면 이 테스트도 함께 수정 필요
    - 이 이중 수정이 git diff 에 반드시 노출 → 조용한 우회 불가
"""
from __future__ import annotations

# 하한 상수 · 이 값 이하로 낮추려면 위 docstring 절차 따를 것
MIN_COST_ROUND_TRIP_PCT: float = 1.0
MIN_SLIPPAGE_PCT: float = 1.0
# L14+ 오늘의 실행 카드 · 사용자 지시서 §1.1 필터 하향 방지 (2026-08-05)
MIN_BULL_PCT_MIN: float = 70.0
MIN_MENTIONS_90D_MIN: int = 10
MIN_MENTIONS_7D_MIN: int = 2
MIN_SL_PCT: float = 10.0                # 손절 완화 방지
MIN_TP_TRIGGER_PCT: float = 15.0
MIN_TRAIL_PCT: float = 7.0
MAX_POSITION_KRW: float = 200_000.0     # 종목당 상한 확대 방지 (RISK §1 · 20만원)


def test_cost_round_trip_pct_not_lowered() -> None:
    """COST_ROUND_TRIP_PCT 하한 방어 · Fable 5 5차."""
    from backend.discovery.serenity.constants import COST_ROUND_TRIP_PCT

    assert COST_ROUND_TRIP_PCT >= MIN_COST_ROUND_TRIP_PCT, (
        f"COST_ROUND_TRIP_PCT={COST_ROUND_TRIP_PCT} < MIN={MIN_COST_ROUND_TRIP_PCT}. "
        "실측 하향 시 이 테스트의 MIN_COST_ROUND_TRIP_PCT 도 함께 갱신하고 "
        "RISK-PRINCIPLES.md §8 · §11 이력에 근거 append 하십시오."
    )


def test_slippage_pct_not_lowered() -> None:
    """SLIPPAGE_PCT 하한 방어 · Fable 5 5차."""
    from backend.discovery.serenity.constants import SLIPPAGE_PCT

    assert SLIPPAGE_PCT >= MIN_SLIPPAGE_PCT, (
        f"SLIPPAGE_PCT={SLIPPAGE_PCT} < MIN={MIN_SLIPPAGE_PCT}. "
        "실측 하향 시 이 테스트의 MIN_SLIPPAGE_PCT 도 함께 갱신하고 "
        "RISK-PRINCIPLES.md §7 · §11 이력에 근거 append 하십시오."
    )


def test_action_card_filters_not_relaxed() -> None:
    """오늘의 실행 카드 필터 (지시서 §1.1) 하향 방지."""
    from backend.discovery.serenity.constants import (
        BULL_PCT_MIN, MENTIONS_90D_MIN, MENTIONS_7D_MIN,
    )
    assert BULL_PCT_MIN >= MIN_BULL_PCT_MIN, "BULL_PCT_MIN 하향은 신호 품질 훼손 · 지시서 §1.1"
    assert MENTIONS_90D_MIN >= MIN_MENTIONS_90D_MIN, "MENTIONS_90D_MIN 표본 축소는 통계 왜곡"
    assert MENTIONS_7D_MIN >= MIN_MENTIONS_7D_MIN, "MENTIONS_7D_MIN 살아있는 관심 축소는 신호 오염"


def test_risk_management_constants_not_relaxed() -> None:
    """손절·익절·포지션 상한 · RISK-PRINCIPLES §1·4·5 완화 방지."""
    from backend.discovery.serenity.constants import (
        SL_PCT, TP_TRIGGER_PCT, TRAIL_PCT, POSITION_KRW,
    )
    # 손절선을 좁히면 (예 -8%) 마이크로캡 노이즈 stopout 위험 (Fable 5 3차)
    assert SL_PCT >= MIN_SL_PCT, f"SL_PCT={SL_PCT} < {MIN_SL_PCT} · Fable 5 마이크로캡 노이즈"
    assert TP_TRIGGER_PCT >= MIN_TP_TRIGGER_PCT, "TP_TRIGGER_PCT 하향은 익절 조기 발동"
    assert TRAIL_PCT >= MIN_TRAIL_PCT, "TRAIL_PCT 하향은 즉시 발동 · Fable 5 -5% → -7%"
    # 포지션 상한 · 20만원 초과 매수 방지 (RISK §1 · 시드 20%)
    assert POSITION_KRW <= MAX_POSITION_KRW, (
        f"POSITION_KRW={POSITION_KRW} > {MAX_POSITION_KRW} · RISK §1 종목당 20% 위반"
    )
