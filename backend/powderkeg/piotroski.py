"""Piotroski F-Score 계산기 · Phase 7-2 조건 8.

9개 항목 (0 또는 1) · 총점 0~9 · 기준 ≥ 6.

수익성 (Profitability):
  §1 ROA > 0                             · 당기순이익 / 총자산 > 0
  §2 CFO > 0                             · 영업활동현금흐름 > 0
  §3 ΔROA > 0                            · 당기 ROA > 전기 ROA
  §4 Accrual: CFO > 당기순이익           · 현금흐름이 순이익보다 큼 (누산 신뢰)

레버리지·유동성·자본조달 (Leverage):
  §5 Δ장기부채비율 감소                  · long_term_debt / total_assets · 감소
  §6 Δ유동비율 증가                      · current_assets / current_liabilities · 증가
  §7 신규 주식 발행 없음                 · shares_outstanding 증가 아님 (≤)

운영 효율성 (Efficiency):
  §8 Δ매출총이익률 개선                  · gross_profit / revenue · 증가
  §9 Δ자산회전율 개선                    · revenue / total_assets · 증가

취급:
  · 항목별 available (데이터 존재) / value (0 또는 1) 반환.
  · N/A 항목은 total_checks 에서 제외 · 판정 시 available 만 카운트.
  · v1 정책: min_score 는 available 기반 상대치 vs 절대 6 (사용자 선택).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FinancialPeriod:
    """단일 회계기간 · 스코어 계산용 필드."""
    net_income: Optional[float] = None
    cash_flow_from_operations: Optional[float] = None
    total_assets: Optional[float] = None
    total_debt: Optional[float] = None                # 장기부채 근사 (v1 · 전체 차입금 사용)
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    shares_outstanding: Optional[float] = None


@dataclass
class FScoreCheck:
    name: str
    available: bool
    passed: Optional[bool]        # available=False 이면 None
    detail: str = ""


@dataclass
class FScoreResult:
    total_score: int              # 통과 항목 수 (available 만)
    available_checks: int         # 계산 가능한 항목 수 (0~9)
    checks: list[FScoreCheck] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """9개 중 계산 가능 비율."""
        return self.available_checks / 9.0


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def calculate_f_score(current: FinancialPeriod, prior: FinancialPeriod) -> FScoreResult:
    """current (당기) + prior (전기) → F-Score.

    부족한 데이터는 항목별 available=False · 총점에서 제외.
    """
    checks: list[FScoreCheck] = []

    # §1 ROA > 0
    roa_c = _safe_div(current.net_income, current.total_assets)
    ok = roa_c is not None
    checks.append(FScoreCheck(
        name="§1 ROA > 0", available=ok,
        passed=(roa_c > 0) if ok else None,
        detail=f"ROA_curr={roa_c:.4f}" if ok else "no_assets_or_ni",
    ))

    # §2 CFO > 0
    cfo = current.cash_flow_from_operations
    ok = cfo is not None
    checks.append(FScoreCheck(
        name="§2 CFO > 0", available=ok,
        passed=(cfo > 0) if ok else None,
        detail=f"CFO={cfo:,.0f}" if ok else "no_cfo",
    ))

    # §3 ΔROA > 0
    roa_p = _safe_div(prior.net_income, prior.total_assets)
    ok = roa_c is not None and roa_p is not None
    checks.append(FScoreCheck(
        name="§3 ΔROA > 0", available=ok,
        passed=(roa_c > roa_p) if ok else None,
        detail=f"ΔROA={(roa_c - roa_p):.4f}" if ok else "no_roa_history",
    ))

    # §4 CFO > NI
    ok = cfo is not None and current.net_income is not None
    checks.append(FScoreCheck(
        name="§4 CFO > NI (Accrual)", available=ok,
        passed=(cfo > current.net_income) if ok else None,
        detail=f"CFO-NI={cfo - current.net_income:,.0f}" if ok else "no_cfo_or_ni",
    ))

    # §5 장기부채비율 감소 (v1 · total_debt / total_assets · 실 장기부채 데이터 없으므로 근사)
    lev_c = _safe_div(current.total_debt, current.total_assets)
    lev_p = _safe_div(prior.total_debt, prior.total_assets)
    ok = lev_c is not None and lev_p is not None
    checks.append(FScoreCheck(
        name="§5 Δ레버리지 감소", available=ok,
        passed=(lev_c < lev_p) if ok else None,
        detail=f"Δ레버리지={lev_c - lev_p:.4f}" if ok else "no_debt_or_assets_history",
    ))

    # §6 유동비율 증가
    cr_c = _safe_div(current.current_assets, current.current_liabilities)
    cr_p = _safe_div(prior.current_assets, prior.current_liabilities)
    ok = cr_c is not None and cr_p is not None
    checks.append(FScoreCheck(
        name="§6 Δ유동비율 증가", available=ok,
        passed=(cr_c > cr_p) if ok else None,
        detail=f"Δ유동비율={cr_c - cr_p:.4f}" if ok else "no_current_ratio_history",
    ))

    # §7 신규 주식 발행 없음 (shares_outstanding 감소 or 동일)
    ok = current.shares_outstanding is not None and prior.shares_outstanding is not None
    checks.append(FScoreCheck(
        name="§7 무증자", available=ok,
        passed=(current.shares_outstanding <= prior.shares_outstanding) if ok else None,
        detail=f"Δshares={current.shares_outstanding - prior.shares_outstanding:,.0f}" if ok else "no_shares_history",
    ))

    # §8 매출총이익률 개선
    gm_c = _safe_div(current.gross_profit, current.revenue)
    gm_p = _safe_div(prior.gross_profit, prior.revenue)
    ok = gm_c is not None and gm_p is not None
    checks.append(FScoreCheck(
        name="§8 Δ매출총이익률 개선", available=ok,
        passed=(gm_c > gm_p) if ok else None,
        detail=f"Δgm={gm_c - gm_p:.4f}" if ok else "no_margin_history",
    ))

    # §9 자산회전율 개선
    at_c = _safe_div(current.revenue, current.total_assets)
    at_p = _safe_div(prior.revenue, prior.total_assets)
    ok = at_c is not None and at_p is not None
    checks.append(FScoreCheck(
        name="§9 Δ자산회전율 개선", available=ok,
        passed=(at_c > at_p) if ok else None,
        detail=f"Δturnover={at_c - at_p:.4f}" if ok else "no_turnover_history",
    ))

    available_checks = sum(1 for c in checks if c.available)
    total_score = sum(1 for c in checks if c.available and c.passed)

    return FScoreResult(
        total_score=total_score,
        available_checks=available_checks,
        checks=checks,
    )
