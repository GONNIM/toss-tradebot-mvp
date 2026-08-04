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
