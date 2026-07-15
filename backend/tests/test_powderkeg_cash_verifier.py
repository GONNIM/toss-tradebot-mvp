"""P7-2b verify_cash_reality 단위 테스트 · 분식 탐지 핵심."""
from __future__ import annotations

import pytest

from backend.powderkeg.cash_verifier import verify_cash_reality


def test_normal_yield_passes():
    """평범한 예금 이자율 · 통과."""
    # 100억 현금 · 이자 3.5억 → 3.5% (required 1.75%)
    r = verify_cash_reality(
        interest_income=350_000_000,
        cash_current=10_000_000_000,
        base_rate=0.0325, margin=0.015,
    )
    assert r.passed is True
    assert r.reason == "ok"
    assert r.implied_yield == pytest.approx(0.035, abs=0.001)


def test_yield_below_threshold_fails():
    """이자율 0.5% · 기준금리 3.25%-1.5%=1.75% 미달 → cash_suspect."""
    r = verify_cash_reality(
        interest_income=50_000_000,
        cash_current=10_000_000_000,
        base_rate=0.0325, margin=0.015,
    )
    assert r.passed is False
    assert r.reason == "yield_below_threshold"
    assert r.implied_yield == pytest.approx(0.005)


def test_zero_interest_with_cash_flags_suspect():
    """현금 100억인데 이자 0 · 명백한 이상 → cash_suspect."""
    r = verify_cash_reality(
        interest_income=0,
        cash_current=10_000_000_000,
    )
    assert r.passed is False
    assert r.reason == "no_interest_income"


def test_none_interest_with_cash_flags_suspect():
    """이자 None (미공시) · 현금 있음 → cash_suspect (관대 처리 X)."""
    r = verify_cash_reality(
        interest_income=None,
        cash_current=10_000_000_000,
    )
    assert r.passed is False
    assert r.reason == "no_interest_income"


def test_no_cash_data_skips():
    """현금 데이터 자체 없음 · 판정 불가 · pass (관대 처리)."""
    r = verify_cash_reality(
        interest_income=100_000_000,
        cash_current=None,
    )
    assert r.passed is True
    assert r.reason == "no_cash_data_skip"


def test_zero_cash_skips_divzero_protection():
    """avg_cash = 0 · 분모 0 방지 · pass."""
    r = verify_cash_reality(
        interest_income=100_000_000,
        cash_current=0,
    )
    assert r.passed is True
    assert r.reason == "avg_cash_non_positive_skip"


def test_avg_uses_prior_when_provided():
    """전기 100억 · 당기 200억 · 평균 150억 · 이자 5억 → 3.33%."""
    r = verify_cash_reality(
        interest_income=500_000_000,
        cash_current=20_000_000_000,
        cash_prior=10_000_000_000,
    )
    assert r.avg_cash == 15_000_000_000
    assert r.implied_yield == pytest.approx(0.0333, abs=0.001)
    assert r.passed is True


def test_boundary_exactly_at_threshold():
    """정확히 required_yield · pass (>= 조건)."""
    # required = 3.25%-1.5% = 1.75% · 이자 1.75억 / 현금 100억
    r = verify_cash_reality(
        interest_income=175_000_000,
        cash_current=10_000_000_000,
        base_rate=0.0325, margin=0.015,
    )
    assert r.passed is True
    assert r.implied_yield == pytest.approx(0.0175, abs=0.0001)


def test_custom_base_rate_and_margin():
    """base_rate=5%, margin=2%p → required=3% · 이자율 2.5% → fail."""
    r = verify_cash_reality(
        interest_income=250_000_000,
        cash_current=10_000_000_000,
        base_rate=0.05, margin=0.02,
    )
    assert r.required_yield == pytest.approx(0.03)
    assert r.passed is False


def test_negative_prior_cash_still_computes():
    """prior 이상값 · 로직 안전성 (실제로는 발생하지 않음)."""
    r = verify_cash_reality(
        interest_income=500_000_000,
        cash_current=20_000_000_000,
        cash_prior=-1_000_000_000,   # 음수 방어 확인
    )
    # avg = (20 - 1) / 2 = 9.5B · yield = 5.26% → pass
    assert r.avg_cash == 9_500_000_000
    assert r.passed is True
