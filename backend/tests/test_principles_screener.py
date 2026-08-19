"""Principles v1.0.2 · 5원칙 스크리너 3값 판정 회귀 테스트.

사용자 지시 (반영 사항 5번): 배당 이력 5년 미만 = FAIL(history_short) · INSUFFICIENT 아님.
"""
from __future__ import annotations

from backend.principles.screener import ScreenerInput, screen


def _base_input(**overrides):
    """PASS 기본 입력 · 개별 필드 override 로 케이스 생성."""
    base = dict(
        ticker="005930",
        name="삼성전자",
        market_cap=500_000e9,          # 500조
        net_income_owner_ttm=80_000e9, # 80조 · PER = 6.25
        operating_income_ttm=60_000e9, # PER 영업 = 8.33
        net_income_owner_3y=[70_000e9, 75_000e9, 80_000e9],  # 3년 흑자
        dividend_total_3y=[18_000e9, 19_000e9, 20_000e9],   # ratio ~0.45
        buyback_cashflow_3y=[14_000e9, 15_000e9, 16_000e9],
        dividend_per_share_5y=[1400.0, 1600.0, 1800.0, 2000.0, 2200.0],  # 5년 증배
        total_liabilities=100_000e9,
        total_equity=200_000e9,        # 부채비율 0.5
        interest_expense_ttm=1_000e9,  # 이자보상배율 60
        is_financial_sector=False,
    )
    base.update(overrides)
    return ScreenerInput(**base)


# ─── PASS ──────────────────────────────────────────────────────


def test_pass_all_five_principles():
    result = screen(_base_input())
    assert result.verdict == "PASS"
    assert result.per_ttm is not None and result.per_ttm < 10
    assert result.payout_ratio_3y_avg is not None and result.payout_ratio_3y_avg >= 0.40
    assert result.dividend_years == 5
    assert result.debt_ratio == 0.5


# ─── 원칙 1 · PER FAIL ────────────────────────────────────────


def test_fail_per_ttm_over_10():
    result = screen(_base_input(net_income_owner_ttm=30_000e9))  # PER = 16.67
    assert result.verdict == "FAIL"
    per_reason = next(r for r in result.reasons if r.code == "per")
    assert per_reason.status == "fail"


def test_fail_per_loss_year_ttm():
    """v1.0.1 loss_handling · TTM ≤ 0 → 원칙 1 자동 fail."""
    result = screen(_base_input(net_income_owner_ttm=-5_000e9))
    assert result.verdict == "FAIL"
    per_reason = next(r for r in result.reasons if r.code == "per")
    assert per_reason.status == "fail"
    assert "≤ 0" in per_reason.note


# ─── 원칙 2 · 주주환원율 FAIL ─────────────────────────────────


def test_fail_shareholder_return_below_40pct():
    result = screen(_base_input(
        dividend_total_3y=[5_000e9, 6_000e9, 7_000e9],
        buyback_cashflow_3y=[3_000e9, 4_000e9, 5_000e9],
    ))
    # ratios: 8/70, 10/75, 12/80 = 0.114, 0.133, 0.150 · avg 0.132 < 0.40
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "shareholder_return")
    assert r.status == "fail"


def test_fail_shareholder_return_loss_year():
    """v1.0.1 loss_handling · 3년 중 1개년 적자 → 원칙 2 자동 fail."""
    result = screen(_base_input(
        net_income_owner_3y=[70_000e9, -10_000e9, 80_000e9],
    ))
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "shareholder_return")
    assert r.status == "fail"
    assert "적자" in r.note


# ─── 원칙 3 · 배당 지속성 ────────────────────────────────────


def test_fail_dividend_history_short_v1_0_2():
    """v1.0.2 · 5년 미만 (신규상장 등) 은 FAIL · INSUFFICIENT 아님."""
    result = screen(_base_input(dividend_per_share_5y=[1000.0, 1200.0, 1400.0]))  # 3년만
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "dividend_continuity")
    assert r.status == "fail"
    assert "history_short" in r.note
    assert r.value["history_short"] is True


def test_fail_dividend_cut_within_5y():
    """5년 중 감배 · 원칙 3 fail (cut_allowed=false)."""
    result = screen(_base_input(
        dividend_per_share_5y=[2000.0, 2200.0, 1800.0, 2000.0, 2200.0],  # 3번째 감배
    ))
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "dividend_continuity")
    assert r.status == "fail"
    assert "감배" in r.note


def test_fail_dividend_zero_year():
    """5년 중 무배당 존재 · 원칙 3 fail."""
    result = screen(_base_input(
        dividend_per_share_5y=[1000.0, 0.0, 1200.0, 1400.0, 1600.0],
    ))
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "dividend_continuity")
    assert r.status == "fail"
    assert "무배당" in r.note


# ─── 원칙 4 · 재무 건전성 ────────────────────────────────────


def test_fail_debt_ratio_over_200pct():
    """부채비율 > 200% · 원칙 4 fail."""
    result = screen(_base_input(
        total_liabilities=500_000e9,   # 부채비율 2.5 > 2.0
    ))
    assert result.verdict == "FAIL"
    r = next(r for r in result.reasons if r.code == "financial_soundness")
    assert r.status == "fail"


def test_skip_financial_sector():
    """금융업 · 원칙 4 skip · 나머지 통과 시 PASS."""
    result = screen(_base_input(
        is_financial_sector=True,
        total_liabilities=None,   # 결측이어도 skip 로 무시
        total_equity=None,
    ))
    assert result.verdict == "PASS"
    r = next(r for r in result.reasons if r.code == "financial_soundness")
    assert r.status == "skip"


# ─── INSUFFICIENT_DATA ─────────────────────────────────────────


def test_insufficient_data_missing_market_cap():
    """market_cap 결측 · P1 계산 불가 · INSUFFICIENT (FAIL 아님)."""
    result = screen(_base_input(market_cap=None))
    assert result.verdict == "INSUFFICIENT_DATA"
    assert "market_cap" in result.missing_fields


def test_insufficient_data_missing_ni_3y():
    """3년 순이익 결측 · P2 계산 불가 · INSUFFICIENT."""
    result = screen(_base_input(net_income_owner_3y=[None, 75_000e9, 80_000e9]))
    assert result.verdict == "INSUFFICIENT_DATA"


def test_fail_wins_over_insufficient():
    """P1 fail + P4 insufficient → verdict=FAIL (fail 우선)."""
    result = screen(_base_input(
        net_income_owner_ttm=-1000e9,  # P1 fail
        total_liabilities=None,        # P4 insufficient
        total_equity=None,
    ))
    assert result.verdict == "FAIL"


# ─── 원칙 5 (분산) skip ────────────────────────────────────────


def test_diversification_always_skip_in_screener():
    """P5 는 스크리너 미강제 · 항상 skip · 게이트 전용."""
    result = screen(_base_input())
    r = next(r for r in result.reasons if r.code == "diversification")
    assert r.status == "skip"


# ─── TTM sanity check (v1.0.2 · 2026-08-18 파싱 오매칭 재발 방지) ────


def test_ttm_sanity_fail_ratio_over_4x():
    """TTM 순이익이 사업보고서 연간의 12배 → INSUFFICIENT_DATA · ttm_sanity_fail (v1.0.3)."""
    result = screen(_base_input(
        net_income_owner_ttm=400_000e9,   # 자본 잘못 매핑 케이스 (400조)
        latest_annual_net_income_owner=33_000e9,  # 실제 연간 33조 · 비율 12.1
    ))
    assert result.verdict == "INSUFFICIENT_DATA"
    ttm_sanity = next(r for r in result.reasons if r.code == "ttm_sanity")
    assert ttm_sanity.status == "insufficient"
    assert "ttm_sanity_fail" in ttm_sanity.note


def test_ttm_sanity_fail_ratio_under_quarter():
    """TTM 이 연간의 10% (파싱 결함 · 값 누락) → INSUFFICIENT_DATA."""
    result = screen(_base_input(
        net_income_owner_ttm=8_000e9,
        latest_annual_net_income_owner=80_000e9,  # 비율 0.1
    ))
    assert result.verdict == "INSUFFICIENT_DATA"


def test_ttm_sanity_pass_within_4x_tolerance():
    """TTM 이 연간의 2.5배 (반도체 초호황 급증) · v1.0.3 완화 · 통과."""
    result = screen(_base_input(
        net_income_owner_ttm=110_000e9,   # 급증 (반기까지 강한 실적)
        latest_annual_net_income_owner=44_000e9,  # 비율 2.5
    ))
    assert result.verdict != "INSUFFICIENT_DATA"
    ttm_sanity_reasons = [r for r in result.reasons if r.code == "ttm_sanity"]
    assert len(ttm_sanity_reasons) == 0  # sanity 검사에서 추가되지 않음


def test_ttm_sanity_pass_within_tolerance():
    """TTM 이 연간과 근접 · sanity check 통과 · 정상 판정 진행."""
    result = screen(_base_input(
        net_income_owner_ttm=80_000e9,
        latest_annual_net_income_owner=80_000e9,  # 비율 1.0
    ))
    assert result.verdict == "PASS"


def test_ttm_sanity_skipped_when_latest_annual_missing():
    """latest_annual 없으면 sanity check skip · 기존 로직으로 판정."""
    result = screen(_base_input(latest_annual_net_income_owner=None))
    assert result.verdict == "PASS"
