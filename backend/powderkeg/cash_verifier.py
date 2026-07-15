"""이자수익 vs 현금성자산 교차검증 · Phase 7-2 조건 6 (분식 탐지 핵심).

지시서 §7-2 조건 6:
    이자수익 / 평균 현금성자산 ≥ (기준금리 − 1.5%p)
    미달 시 → `cash_suspect` 플래그 후 제외.

취지: 재무제표상 현금이 많다고 표시되지만 실제 이자수익이 낮으면
      현금이 사실상 존재하지 않을 가능성 (분식 or 무담보 대여 등).

평균 현금성자산 · 당기말 + 전기말 / 2 (또는 당기말만 · 데이터 없을 때).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CashRealityResult:
    """검증 결과."""
    passed: bool                      # True = 정상 · False = cash_suspect
    interest_income: Optional[float]
    avg_cash: Optional[float]
    implied_yield: Optional[float]    # 이자수익 / 평균 현금성자산
    required_yield: float             # 기준금리 - 1.5%p
    reason: str                       # "ok" / "no_interest_income" / "no_cash_data" / "yield_below_threshold" 등


def verify_cash_reality(
    interest_income: Optional[float],
    cash_current: Optional[float],
    cash_prior: Optional[float] = None,
    base_rate: float = 0.0325,
    margin: float = 0.015,
) -> CashRealityResult:
    """이자수익 정합성 검증.

    Args:
        interest_income: 당기 이자수익 (또는 금융수익)
        cash_current: 당기말 현금성자산 (현금+단기금융상품 합산)
        cash_prior: 전기말 현금성자산 · None 이면 당기 만 사용
        base_rate: 기준금리 (연 · 예 3.25% = 0.0325)
        margin: 허용 하락 폭 (기본 1.5%p)

    Returns:
        CashRealityResult · passed=False 이면 cash_suspect 플래그.

    로직:
        1. 이자수익 없거나 0 이면 cash_suspect (현금 있는데 이자 0 은 이상)
        2. 현금성자산 없으면 skip (판정 불가 · passed=True 관대 처리)
        3. avg_cash = (cash_current + cash_prior) / 2 or cash_current
        4. avg_cash <= 0 이면 skip (분모 0 방지)
        5. implied_yield = interest_income / avg_cash
        6. implied_yield >= (base_rate - margin) 이면 pass
    """
    required_yield = base_rate - margin

    if cash_current is None:
        return CashRealityResult(
            passed=True, interest_income=interest_income, avg_cash=None,
            implied_yield=None, required_yield=required_yield,
            reason="no_cash_data_skip",
        )

    # avg 계산
    if cash_prior is not None:
        avg_cash = (cash_current + cash_prior) / 2.0
    else:
        avg_cash = cash_current

    if avg_cash <= 0:
        return CashRealityResult(
            passed=True, interest_income=interest_income, avg_cash=avg_cash,
            implied_yield=None, required_yield=required_yield,
            reason="avg_cash_non_positive_skip",
        )

    # 이자수익 결측/0 이면 · 현금이 있는데 이자가 없다는 것은 의심스러움
    if interest_income is None or interest_income == 0:
        return CashRealityResult(
            passed=False, interest_income=interest_income, avg_cash=avg_cash,
            implied_yield=0.0, required_yield=required_yield,
            reason="no_interest_income",
        )

    implied_yield = interest_income / avg_cash

    if implied_yield >= required_yield:
        return CashRealityResult(
            passed=True, interest_income=interest_income, avg_cash=avg_cash,
            implied_yield=implied_yield, required_yield=required_yield,
            reason="ok",
        )
    return CashRealityResult(
        passed=False, interest_income=interest_income, avg_cash=avg_cash,
        implied_yield=implied_yield, required_yield=required_yield,
        reason="yield_below_threshold",
    )
