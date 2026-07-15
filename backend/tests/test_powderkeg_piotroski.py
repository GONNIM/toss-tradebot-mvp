"""P7-2c Piotroski F-Score 단위 테스트 (알려진 예제 검증)."""
from __future__ import annotations

import pytest

from backend.powderkeg.piotroski import FinancialPeriod, calculate_f_score


def _period(**kw) -> FinancialPeriod:
    return FinancialPeriod(**kw)


def test_perfect_9_score_all_checks_pass():
    """이상적 우량 기업 · 9/9 통과."""
    current = _period(
        net_income=100, cash_flow_from_operations=150,   # CFO > NI · §4
        total_assets=1000, total_debt=200,               # 레버리지 0.20
        current_assets=500, current_liabilities=100,     # 유동비율 5.0
        revenue=800, gross_profit=400,                   # gm 0.5
        shares_outstanding=1000,
    )
    prior = _period(
        net_income=80, cash_flow_from_operations=90,
        total_assets=900, total_debt=250,                # 레버리지 0.278 (더 높음)
        current_assets=400, current_liabilities=100,     # 유동비율 4.0
        revenue=700, gross_profit=280,                   # gm 0.4
        shares_outstanding=1000,
    )
    r = calculate_f_score(current, prior)
    assert r.available_checks == 9
    assert r.total_score == 9


def test_zero_score_worst_case():
    """모든 지표 악화 · 0/9."""
    current = _period(
        net_income=-100, cash_flow_from_operations=-50,   # 손실 + CFO 음수
        total_assets=1000, total_debt=400,                # 레버리지 0.4
        current_assets=200, current_liabilities=300,      # 유동비율 0.67
        revenue=500, gross_profit=100,                    # gm 0.2
        shares_outstanding=1500,                          # 유상증자
    )
    prior = _period(
        net_income=-50, cash_flow_from_operations=-20,
        total_assets=1100, total_debt=300,                # 레버리지 0.273 (더 낮음 = 개선 X)
        current_assets=400, current_liabilities=300,      # 유동비율 1.33 (감소 = 개선 X)
        revenue=600, gross_profit=180,                    # gm 0.3 (감소)
        shares_outstanding=1000,
    )
    r = calculate_f_score(current, prior)
    assert r.available_checks == 9
    # 유의: 손실 기업이라도 §4 (CFO > NI) 는 CFO=-50 > NI=-100 통과 가능.
    # Piotroski 특성 · 손실이 클수록 CFO 우세 → §4 위양성.
    # 실 worst case 는 1/9 · 나머지 8 fail.
    assert r.total_score == 1


def test_missing_shares_reduces_available():
    """shares_outstanding 없음 · §7 available=False → 8/8 통과."""
    current = _period(
        net_income=100, cash_flow_from_operations=150,
        total_assets=1000, total_debt=200,
        current_assets=500, current_liabilities=100,
        revenue=800, gross_profit=400,
        shares_outstanding=None,
    )
    prior = _period(
        net_income=80, cash_flow_from_operations=90,
        total_assets=900, total_debt=250,
        current_assets=400, current_liabilities=100,
        revenue=700, gross_profit=280,
        shares_outstanding=None,
    )
    r = calculate_f_score(current, prior)
    assert r.available_checks == 8
    assert r.total_score == 8   # §7 제외 · 나머지 8/8 통과
    shares_check = next(c for c in r.checks if "무증자" in c.name)
    assert shares_check.available is False
    assert shares_check.passed is None


def test_missing_cfo_only_affects_two_checks():
    """CFO 없음 · §2 · §4 available=False."""
    current = _period(
        net_income=100, cash_flow_from_operations=None,
        total_assets=1000, total_debt=200,
        current_assets=500, current_liabilities=100,
        revenue=800, gross_profit=400,
        shares_outstanding=1000,
    )
    prior = _period(
        net_income=80, total_assets=900, total_debt=250,
        current_assets=400, current_liabilities=100,
        revenue=700, gross_profit=280, shares_outstanding=1000,
    )
    r = calculate_f_score(current, prior)
    assert r.available_checks == 7      # §2, §4 제외
    cfo_check = next(c for c in r.checks if "CFO > 0" in c.name)
    acc_check = next(c for c in r.checks if "Accrual" in c.name)
    assert cfo_check.available is False
    assert acc_check.available is False


def test_partial_score_realistic():
    """현실적 · 일부 통과 · 일부 실패."""
    current = _period(
        net_income=100, cash_flow_from_operations=120,   # §1 pass, §2 pass, §4 pass (CFO>NI)
        total_assets=1000, total_debt=200,               # §5 · 필요 prior
        current_assets=500, current_liabilities=100,
        revenue=800, gross_profit=400,
        shares_outstanding=1000,
    )
    prior = _period(
        net_income=120, cash_flow_from_operations=100,   # §3 fail (ROA 감소 · 100/1000 < 120/900)
        total_assets=900, total_debt=180,                # 레버리지 0.20 (동일) · §5 fail (>=)
        current_assets=400, current_liabilities=100,     # 유동비율 4.0 → 5.0 · §6 pass
        revenue=700, gross_profit=280,                   # gm 0.4 → 0.5 · §8 pass
        shares_outstanding=1000,                         # §7 pass (동일)
    )
    r = calculate_f_score(current, prior)
    assert r.available_checks == 9
    # 통과 예상: §1(0.10>0), §2(CFO>0), §4(CFO>NI), §6, §7, §8, §9(0.8>0.78)
    # 실패 예상: §3(0.10<0.133), §5(0.20 == 0.20 · < 조건이므로 fail)
    assert r.total_score == 7


def test_boundary_shares_equal_passes():
    """shares_outstanding 동일 · §7 pass (≤ 조건)."""
    current = _period(shares_outstanding=1000, net_income=100, total_assets=1000)
    prior = _period(shares_outstanding=1000, net_income=100, total_assets=1000)
    r = calculate_f_score(current, prior)
    shares_check = next(c for c in r.checks if "무증자" in c.name)
    assert shares_check.available is True
    assert shares_check.passed is True


def test_coverage_property():
    """coverage = available / 9."""
    current = _period(net_income=100, total_assets=1000)
    prior = _period(net_income=80, total_assets=900)
    r = calculate_f_score(current, prior)
    # §1 · §3 만 available (net_income · total_assets 있음)
    assert r.available_checks == 2
    assert r.coverage == pytest.approx(2 / 9)


def test_all_empty_returns_zero_available():
    r = calculate_f_score(_period(), _period())
    assert r.available_checks == 0
    assert r.total_score == 0
