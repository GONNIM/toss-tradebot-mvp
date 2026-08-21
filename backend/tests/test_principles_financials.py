"""Principles v1.0.2 · TTM 누적 분해 + reasons_json 단위 테스트.

사용자 지시 (반영 사항 2번): TTM 계산 시 누적값 분해 · 연말 Q4 = 사업보고서 연간값 − 3Q 누적 케이스 포함.
"""
from __future__ import annotations

from backend.principles.financials import (
    PrinciplesFinancials,
    cumulative_to_quarter,
    parse_principles_financials,
    ttm_sum,
)
from backend.discovery.data_sources.dart.client import DartFinancialItem


# ─── cumulative_to_quarter ─────────────────────────────────────


def test_cumulative_to_quarter_basic():
    """정상 4개 분기 누적 → Q단독 분해."""
    cum = {1: 100.0, 2: 250.0, 3: 400.0, 4: 600.0}
    q = cumulative_to_quarter(cum)
    assert q[1] == 100.0
    assert q[2] == 150.0
    assert q[3] == 150.0
    assert q[4] == 200.0


def test_cumulative_to_quarter_q4_year_end():
    """연말 Q4 = 사업보고서 연간값 − 3Q 누적 (사용자 지시 명시 케이스)."""
    # 사업보고서 (Q4=연간) 950억 - 3Q 누적 700억 = Q4단독 250억
    cum = {1: 200.0, 2: 400.0, 3: 700.0, 4: 950.0}
    q = cumulative_to_quarter(cum)
    assert q[4] == 250.0


def test_cumulative_to_quarter_missing_q1():
    """Q1 결측 → Q2 이후 계산 불가."""
    cum = {1: None, 2: 250.0, 3: 400.0, 4: 600.0}
    q = cumulative_to_quarter(cum)
    assert q[1] is None
    assert q[2] is None  # Q1 없이 Q2 단독 계산 불가
    # Q3 = Q3_cum - Q2_cum 은 계산 가능
    assert q[3] == 150.0
    assert q[4] == 200.0


def test_cumulative_to_quarter_q4_missing():
    """Q4 (사업보고서) 결측 → Q4 단독 None · TTM 정합 불가."""
    cum = {1: 100.0, 2: 250.0, 3: 400.0, 4: None}
    q = cumulative_to_quarter(cum)
    assert q[1] == 100.0
    assert q[2] == 150.0
    assert q[3] == 150.0
    assert q[4] is None


def test_cumulative_to_quarter_loss_year():
    """적자 연도 (누적 음수) 도 정상 분해."""
    # Q1 -50, 누적 Q2 -120 (Q2단독 -70), Q3 -180 (Q3단독 -60), 연간 -250 (Q4단독 -70)
    cum = {1: -50.0, 2: -120.0, 3: -180.0, 4: -250.0}
    q = cumulative_to_quarter(cum)
    assert q[1] == -50.0
    assert q[2] == -70.0
    assert q[3] == -60.0
    assert q[4] == -70.0


# ─── ttm_sum ───────────────────────────────────────────────────


def test_ttm_sum_recent_4():
    """분기 단독 6개 → 최근 4개 (Q3~) 합산."""
    series = [100.0, 150.0, 150.0, 200.0, 180.0, 220.0]
    assert ttm_sum(series) == 150.0 + 200.0 + 180.0 + 220.0


def test_ttm_sum_exactly_4():
    """정확히 4개 · 그대로 합산."""
    assert ttm_sum([100.0, 150.0, 150.0, 200.0]) == 600.0


def test_ttm_sum_less_than_4_returns_none():
    """4개 미만 · 정합 불가 · None."""
    assert ttm_sum([100.0, 150.0]) is None


def test_ttm_sum_with_none_returns_none():
    """최근 4개 중 하나라도 None · TTM 정합 불가."""
    assert ttm_sum([100.0, 150.0, None, 200.0]) is None
    assert ttm_sum([100.0, 150.0, 150.0, None]) is None


def test_ttm_sum_loss_year_valid():
    """적자 4개 분기 (음수) 도 정상 합산 · 원칙 1 (P1 loss_handling) 은 별도 판정."""
    assert ttm_sum([-50.0, -70.0, -60.0, -70.0]) == -250.0


# ─── parse_principles_financials ───────────────────────────────


def _mk(
    account_id: str,
    account_nm: str,
    amount: float,
    sj_div: str = "BS",
    add_amount: float | None = None,
) -> DartFinancialItem:
    return DartFinancialItem(
        account_id=account_id,
        account_nm=account_nm,
        sj_div=sj_div,
        fs_div="CFS",
        fs_nm="",
        thstrm_amount=amount,
        thstrm_add_amount=add_amount,
        frmtrm_amount=None,
        ord=1,
    )


def test_parse_captures_net_income_owner():
    """지배주주순이익 (P1·P2 분자) · account_id 매칭."""
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업의 소유주에게 귀속되는 당기순이익", 500e9, "IS"),
        _mk("ifrs-full_ProfitLoss", "당기순이익", 550e9, "IS"),
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner == 500e9  # owner 우선


def test_parse_falls_back_to_net_income_when_owner_missing():
    """지배주주순이익 미매치 시 총 당기순이익 로 fallback (필드는 net_income 저장)."""
    items = [
        _mk("ifrs-full_ProfitLoss", "당기순이익", 550e9, "IS"),
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner is None
    assert f.net_income == 550e9


def test_parse_captures_debt_ratio_fields():
    """부채총계·자본총계 (P4)."""
    items = [
        _mk("ifrs-full_Liabilities", "부채총계", 3000e9, "BS"),
        _mk("ifrs-full_Equity", "자본총계", 2500e9, "BS"),
    ]
    f = parse_principles_financials(items)
    assert f.total_liabilities == 3000e9
    assert f.total_equity == 2500e9


def test_parse_captures_interest_expense():
    """이자비용 (P4 이자보상배율 분모)."""
    items = [
        _mk("ifrs-full_FinanceCosts", "금융비용", 80e9, "IS"),
    ]
    f = parse_principles_financials(items)
    assert f.interest_expense == 80e9


def test_parse_captures_buyback_negative_value():
    """자기주식 취득 · 현금흐름표 음수 (유출) 그대로 저장 · 절대값 변환은 caller 책임."""
    items = [
        _mk("ifrs-full_PaymentsForRepurchaseOfEntitysOwnShares",
            "자기주식의 취득", -150e9, "CF"),
    ]
    f = parse_principles_financials(items)
    assert f.buyback_cashflow == -150e9  # 파서는 원본 부호 유지


def test_parse_by_account_nm_fallback():
    """account_id 없는 경우 (한글명 fallback)."""
    items = [
        _mk("", "부채총계", 3000e9, "BS"),
        _mk("", "자본총계", 2500e9, "BS"),
    ]
    f = parse_principles_financials(items)
    assert f.total_liabilities == 3000e9
    assert f.total_equity == 2500e9


# ─── 2026-08-18 fix · 지배주주 vs 전체 · 자본 계정 오매칭 방지 ─────


def test_parse_rejects_equity_account_for_net_income_owner():
    """자본 계정 ('지배기업의 소유주에게 귀속되는 지분/자본') 이 net_income_owner 로 오매칭 안됨.

    사고 (2026-08-18 · 삼성전자 관측): 기존 keyword '지배기업 소유주' 가 substring 매칭이라
    자본 계정도 잡음. keyword 를 '당기순이익' 명시 문구로 엄격화 (v1.0.2 fix).
    """
    items = [
        _mk("", "지배기업의 소유주에게 귀속되는 지분", 400e12, "BS"),  # 자본 400조
        _mk("", "당기순이익", 33e12, "IS"),  # 실제 순이익 33조
    ]
    f = parse_principles_financials(items)
    # 자본 계정은 net_income_owner 로 매치되면 안 됨
    assert f.net_income_owner is None
    # 총 당기순이익 은 fallback net_income 로 매치
    assert f.net_income == 33e12


def test_parse_accepts_correct_owner_net_income():
    """정확 문구 '지배기업의 소유주에게 귀속되는 당기순이익' 은 net_income_owner 로 매치."""
    items = [
        _mk("", "지배기업의 소유주에게 귀속되는 당기순이익", 33e12, "IS"),
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner == 33e12


# ─── v1.0.6-rev4 · sj_div 필터 회귀 (2026-08-20 verified 표본 사고) ───


def test_parse_sce_rejected_for_net_income_owner():
    """SCE (자본변동표) 안의 ProfitLossAttributableToOwnersOfParent 는 배제 (신규 fix).

    사고: 2026-08-20 verified 표본 대조에서 4/5 종목이 SCE 값 (자본 변동) 을
    순이익으로 저장해 부풀림 (S-Oil 5145억 vs 원본 10.09조 등).
    """
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 500e9, "SCE"),  # SCE · 배제되어야
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 10_090e9, "IS"),  # IS · 채택
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner == 10_090e9  # IS 값 · SCE 값 배제


def test_parse_cis_accepted_for_net_income_owner():
    """CIS (포괄손익계산서) 는 IS 대신 허용 · 포괄손익만 있는 기업 대응."""
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 5_000e9, "CIS"),
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner == 5_000e9


def test_parse_bs_only_for_equity_accounts():
    """자본총계 는 BS 만 매치 · SCE 안의 Equity 계정 배제."""
    items = [
        _mk("ifrs-full_Equity", "자본총계", 100e12, "SCE"),  # 배제
        _mk("ifrs-full_Equity", "자본총계", 200e12, "BS"),   # 채택
    ]
    f = parse_principles_financials(items)
    assert f.total_equity == 200e12


def test_parse_cf_only_for_buyback():
    """자기주식 취득은 CF (현금흐름표) 만 · SCE 안의 자기주식 항목 배제."""
    items = [
        _mk("ifrs-full_PaymentsForRepurchaseOfEntitysOwnShares",
            "자기주식의 취득", 100e9, "SCE"),  # 배제
        _mk("ifrs-full_PaymentsForRepurchaseOfEntitysOwnShares",
            "자기주식의 취득", -150e9, "CF"),  # 채택
    ]
    f = parse_principles_financials(items)
    assert f.buyback_cashflow == -150e9


def test_parse_ssdi_regression_2026_q2():
    """삼성SDI 2026 Q2 반기 · 회귀 방지 (정상 케이스 · 파서 정확 매치).

    실제 DART 원본: 지배기업 소유주지분 +3421.9억 (IS)
    """
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 342190000000.0, "IS"),
    ]
    f = parse_principles_financials(items)
    assert f.net_income_owner == 342190000000.0
    assert "IS" in f.matched.get("net_income_owner", "")


def test_parse_fixtures_verified_sample_recovery():
    """verified 표본 4종 (두산·S-Oil·대한항공·한진칼) 실 응답 시뮬레이션.

    fix 전: SCE 안의 계정 잡음 → 부풀림 (7~20배)
    fix 후: IS 안의 계정 정확 매치
    """
    # 두산 2026 Q2 · DART 원본 +2.61조 (IS) · 이전 API 값 3551억 (SCE 오염)
    items_doosan = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 355148000000.0, "SCE"),  # 이전 오염 값
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 2_614e9, "IS"),  # 실 값
    ]
    f = parse_principles_financials(items_doosan)
    assert f.net_income_owner == 2_614e9
    # S-Oil · 원본 10.09조 vs 이전 5145억 (SCE)
    items_soil = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 514584000000.0, "SCE"),
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 10_090e9, "IS"),
    ]
    f = parse_principles_financials(items_soil)
    assert f.net_income_owner == 10_090e9


# ─── v1.0.7 회귀 · thstrm_add_amount 계약 (2026-08-21) ─────────
#
# (a) 삼전 케이스 · 특이 회사 · thstrm 에 누적이 담김 · add=None → fallback 발동
# (b) 표준 규약 케이스 · thstrm=단독·add=누적 · add 우선 채택 · fallback 없음
# (c) add 부재 fallback 케이스 · 플래그 세팅 확인 (a 와 동일 · 명시 케이스)


def test_reg_a_samsung_standard_regime_add_used_and_q_decomposition():
    """삼전 실측 (2026-08-21 dump6.log) · 표준 규약 · thstrm=Q2단독·add=H1누적.

    2026-08-21 [2a] dump 로 확진:
      IS `ifrs-full_ProfitLossAttributableToOwnersOfParent`
        · thstrm = 71.269조 (Q2 단독 3M)
        · add    = 118.371조 (H1 누적 6M · = 원문 확인 대기)
        · 검증: Q1 캐시 47.101 + Q2 단독 71.269 ≈ 118.370 ≈ add · 표준 규약 정합
    add 우선 채택 → fallback 미발동 · 파서 결과 net_income_owner = add (누적).

    폐기된 단언 (2026-08-21):
      - "thstrm=누적 · add=None" 특이 케이스 · 실존 미확인 (add 부재 방어는
        test_reg_c 가 커버). 픽스처 삭제.
      - TTM 110.60 등가 · 폐기된 [0] 감사 전제 (삼전 캐시=H1 누적) 의 산물.
        실제로는 캐시 71.269 가 Q2 단독 · TTM 정합은 우연 상쇄였음.

    대체 단언:
      - 원문 누적 픽스처의 분해값 (Q2단독 = H1 − Q1 = 118.371 − 47.101 = 71.270)
        이 실측 thstrm (71.269) 과 ±0.1% 이내 정합.
    """
    # 삼전 2026 Q2 반기 · IS Owner · 실측 값
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배회사지분 반기순이익", 71.269e12, "IS",
            add_amount=118.371e12),
    ]
    f = parse_principles_financials(items, reprt_code="11012")
    # 파서는 add 우선 채택 · 캐시 저장값 = H1 누적
    assert f.net_income_owner == 118.371e12
    # fallback 미발동 (표준 규약 정합)
    assert not f.fallback_fields

    # 분해값 정합 · Q2 단독 = H1 − Q1 = 118.371 − 47.101 = 71.270
    q1_cum = 47.101e12
    h1_cum = f.net_income_owner
    q2_standalone = h1_cum - q1_cum
    assert q2_standalone > 0
    # 실측 thstrm (Q2 단독) 71.269 와 ±0.1% 이내
    assert abs(q2_standalone - 71.269e12) / 71.269e12 < 0.001


def test_reg_b_standard_regime_thstrm_and_add_present_uses_add():
    """표준 규약 · 반기 CIS Owner · thstrm=단독 · add=누적 · add 우선 채택.

    5종목 (삼성SDI·두산·S-Oil·대한항공·한진칼) 이 이 케이스 · 원문 반기값 = add.
    """
    # 006400 삼성SDI 반기 · thstrm=Q2단독 3421.9억 · add=반기누적 3140.5억 (원문값)
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업지분", 342.19e9, "CIS", add_amount=314.05e9),
    ]
    f = parse_principles_financials(items, reprt_code="11012")
    assert f.net_income_owner == 314.05e9  # add 우선
    assert not f.fallback_fields  # fallback 없음 (정합)

    # 000150 두산 반기 · thstrm=Q2단독 3551.5억 · add=반기누적 3942.7억
    items_doosan = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분", 355.148e9, "IS", add_amount=394.268e9),
    ]
    f = parse_principles_financials(items_doosan, reprt_code="11012")
    assert f.net_income_owner == 394.268e9
    assert not f.fallback_fields


def test_reg_c_add_missing_fallback_flag_set():
    """add 부재 fallback 케이스 · thstrm 사용 + fallback_fields 플래그 발생.

    회사 응답이 반기·3분기에서 add 를 안 주는 특이 케이스 (삼전 스타일 확장).
    필드별 (revenue/op/ni_owner/interest_expense/buyback) 모두 add=None 이면 각각 fallback.
    """
    # 반기 · 5개 흐름 계정 · 모두 add=None · thstrm 만
    items = [
        _mk("ifrs-full_Revenue", "매출액", 1e12, "IS", add_amount=None),
        _mk("ifrs-full_ProfitLossFromOperatingActivities", "영업이익",
            2e11, "IS", add_amount=None),
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업지분", 5e10, "CIS", add_amount=None),
        _mk("ifrs-full_FinanceCosts", "금융비용", 3e9, "IS", add_amount=None),
        _mk("ifrs-full_PaymentsForRepurchaseOfEntitysOwnShares",
            "자기주식의 취득", -1e9, "CF", add_amount=None),
    ]
    f = parse_principles_financials(items, reprt_code="11012")
    assert f.revenue == 1e12
    assert f.operating_income == 2e11
    assert f.net_income_owner == 5e10
    assert f.interest_expense == 3e9
    assert f.buyback_cashflow == -1e9
    # 5개 흐름 계정 모두 fallback 플래그 세팅
    assert f.fallback_fields == {
        "revenue_cum",
        "operating_income_cum",
        "net_income_owner_cum",
        "interest_expense_cum",
        "buyback_cashflow_cum",
    }


def test_reg_c_add_missing_q1_no_fallback():
    """1분기(11013) · add 부재는 정상 (needs_add=False · thstrm=누적=단독)."""
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업지분", 5e10, "CIS", add_amount=None),
    ]
    f = parse_principles_financials(items, reprt_code="11013")
    assert f.net_income_owner == 5e10
    assert not f.fallback_fields  # Q1·사업보고서는 fallback 개념 없음


def test_reg_c_add_missing_annual_no_fallback():
    """사업보고서(11011) · add 부재도 정상 (thstrm=연간 누적)."""
    items = [
        _mk("ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업지분", 1e12, "CIS", add_amount=None),
    ]
    f = parse_principles_financials(items, reprt_code="11011")
    assert f.net_income_owner == 1e12
    assert not f.fallback_fields
