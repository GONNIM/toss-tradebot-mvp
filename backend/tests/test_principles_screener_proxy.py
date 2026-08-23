"""charter v1.0.9 · Owner 세분 없는 회사 (net_income 대체) NCI≈0 프록시 판정 테스트.

3 경로:
  1. 허용 · NCI 부재 (파싱 실패 or 계정 없음) · 100% 지배 회사
  2. 허용 · |NCI| < total_equity × 0.01 (1% 이하)
  3. 불허 · |NCI| ≥ total_equity × 0.01 (1% 초과 · INSUFFICIENT_DATA)

실증 근거: 010950 S-Oil · 2026Q2 총자본 10.086조 · 지배귀속자본 = 자본총계
(사용자 원문 확인 · NCI=0 · 100% 지배).
"""
from __future__ import annotations

from backend.principles.screener import ScreenerInput, screen


def _base_input(**over):
    """5원칙 나머지 pass 가능한 기본 인풋 · Owner 프록시 판정만 격리 테스트."""
    kw = dict(
        ticker="010950",
        name="S-Oil (proxy test)",
        market_cap=10_000e9,
        net_income_owner_ttm=1_000e9,
        operating_income_ttm=1_200e9,
        net_income_owner_3y=[800e9, 900e9, 1_000e9],
        dividend_total_3y=[400e9, 450e9, 500e9],
        buyback_cashflow_3y=[0.0, 0.0, 0.0],
        dividend_per_share_5y=[100, 150, 200, 250, 300],
        total_liabilities=17_000e9,
        total_equity=10_000e9,
        interest_expense_ttm=100e9,
        is_financial_sector=False,
        latest_annual_net_income_owner=1_000e9,
        q_yoy=0.1,
        q_yoy_base_current=1_000e9,
        q_yoy_base_prev=900e9,
        net_income_source_account="당기순이익(손실)[CIS]",
        noncontrolling_interest_snapshot=None,
    )
    kw.update(over)
    return ScreenerInput(**kw)


def test_proxy_allowed_when_nci_absent():
    """경로 1 · NCI 파싱 실패 (None) · 100% 지배 회사 프록시 허용."""
    inp = _base_input(noncontrolling_interest_snapshot=None)
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert any(r.status == "pass" for r in sanity_reasons)
    assert any("NCI absent" in (r.note or "") for r in sanity_reasons)
    assert v.verdict != "INSUFFICIENT_DATA"


def test_proxy_allowed_when_nci_below_1pct():
    """경로 2 · |NCI| < total_equity × 0.01 · 프록시 허용 + ratio 기록."""
    inp = _base_input(
        total_equity=10_000e9,
        noncontrolling_interest_snapshot=50e9,
    )
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert any(r.status == "pass" for r in sanity_reasons)
    pass_reason = [r for r in sanity_reasons if r.status == "pass"][0]
    assert "NCI ratio" in (pass_reason.note or "")
    assert "0.50%" in (pass_reason.note or "")
    assert v.verdict != "INSUFFICIENT_DATA"


def test_proxy_denied_when_nci_above_1pct():
    """경로 3 · |NCI| ≥ total_equity × 0.01 · 프록시 불허 · INSUFFICIENT_DATA."""
    inp = _base_input(
        total_equity=10_000e9,
        noncontrolling_interest_snapshot=500e9,
    )
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert any(r.status == "insufficient" for r in sanity_reasons)
    denied = [r for r in sanity_reasons if r.status == "insufficient"][0]
    assert "owner_proxy_denied" in (denied.note or "")
    assert v.verdict == "INSUFFICIENT_DATA"


def test_proxy_denied_when_total_equity_none():
    """경로 4 (2026-08-23 사용자 보강) · total_equity=None + NCI=None → INSUFFICIENT.

    BS 파싱 자체가 실패 (total_equity 결측) 인 경우 프록시 후보 자격 상실.
    NCI None 을 absent 로 오해석해 프록시 허용 열지 않도록 방어. account_mismatch
    로 자연 INSUFFICIENT.
    """
    inp = _base_input(
        total_equity=None,
        noncontrolling_interest_snapshot=None,
        net_income_source_account="당기순이익(손실)[CIS]",
    )
    v = screen(inp)
    # sanity insufficient (프록시 미발동 · account_mismatch 경로)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert any(r.status == "insufficient" for r in sanity_reasons)
    # owner_ni_proxy_total pass 는 발동 안 함
    assert not any(
        r.status == "pass" and "owner_ni_proxy_total" in (r.note or "")
        for r in sanity_reasons
    )
    assert v.verdict == "INSUFFICIENT_DATA"


def test_allowed_account_v1_0_9_hynix_style_substring():
    """v1.0.9 신규 whitelist · SK하이닉스 스타일 '지배기업의 소유주지분' 통과."""
    inp = _base_input(net_income_source_account="지배기업의 소유주지분[CIS]")
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert not any(
        "account_mismatch" in (r.note or "") for r in sanity_reasons
    ), f"account_mismatch 오탐 · reasons={[r.note for r in sanity_reasons]}"


def test_allowed_account_v1_0_9_daechang_substring():
    """v1.0.9 신규 · '지배기업지분 반기손이익' (대창 실증) 통과."""
    inp = _base_input(net_income_source_account="지배기업지분 반기손이익(손실)[CIS]")
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert not any("account_mismatch" in (r.note or "") for r in sanity_reasons)


def test_allowed_account_v1_0_9_aseasement_substring():
    """v1.0.9 신규 · '지배기업의 소유지분' (아세아시멘트 실증) 통과."""
    inp = _base_input(net_income_source_account="지배기업의 소유지분[CIS]")
    v = screen(inp)
    sanity_reasons = [r for r in v.reasons if r.code == "ttm_sanity"]
    assert not any("account_mismatch" in (r.note or "") for r in sanity_reasons)
