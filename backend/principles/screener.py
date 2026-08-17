"""저평가 우량주 5원칙 스크리너 (v1.0.2).

입력: 종목별 재무 캐시 + 배당 이력 + 시가총액 + 산업분류.
출력: verdict (PASS/FAIL/INSUFFICIENT_DATA) + reasons_json (5원칙 전체 근거).

임계값은 charter.json 에서 조회 (하드코딩 금지).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.principles.charter import get_threshold

logger = logging.getLogger(__name__)


VerdictType = str  # "PASS" | "FAIL" | "INSUFFICIENT_DATA"


@dataclass
class PrincipleReason:
    """단일 원칙 판정 근거."""
    code: str
    status: str  # "pass" | "fail" | "skip" | "insufficient"
    value: Any = None
    threshold: Any = None
    note: str = ""


@dataclass
class ScreenerVerdict:
    """5원칙 종합 판정 결과."""
    verdict: VerdictType
    reasons: list[PrincipleReason] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    # 저장용 요약 지표 (models.PrinciplesResult 컬럼)
    per_ttm: Optional[float] = None
    per_operating: Optional[float] = None
    payout_ratio_3y_avg: Optional[float] = None
    dividend_years: Optional[int] = None
    dividend_cut: Optional[bool] = None
    debt_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None


@dataclass
class ScreenerInput:
    """스크리너 1종목 입력."""
    ticker: str
    name: Optional[str]
    market_cap: Optional[float]                    # 원 단위 · 현재 시가총액
    net_income_owner_ttm: Optional[float]          # 원 · TTM 지배주주순이익
    operating_income_ttm: Optional[float]          # 원 · TTM 영업이익
    # 최근 3개 회계연도 (연간)
    net_income_owner_3y: list[Optional[float]]     # [Y-2, Y-1, Y] 원
    dividend_total_3y: list[Optional[float]]       # 배당총액 3년 (원)
    buyback_cashflow_3y: list[Optional[float]]     # 자기주식 취득액 3년 (절대값 · 원)
    # 배당 이력 5년 (DPS · 원)
    dividend_per_share_5y: list[Optional[float]]   # [Y-4, ..., Y] · 회계연도 기준
    # 재무 건전성 (최신 분기)
    total_liabilities: Optional[float]
    total_equity: Optional[float]
    interest_expense_ttm: Optional[float]
    # 산업
    is_financial_sector: bool


def screen(inp: ScreenerInput) -> ScreenerVerdict:
    """5원칙 검증 · 3값 판정.

    규칙:
      - 필수 재무 결측 다수 → INSUFFICIENT_DATA (원칙 계산 자체 불가)
      - 배당 이력 5년 미만 → FAIL(history_short) · INSUFFICIENT 아님 (v1.0.2)
      - 원칙 4 금융업 skip
      - 원칙 5 (분산) 은 종목 단위 아님 · 스크리너 결과에는 미포함 · 게이트에서 강제
      - 모든 원칙 pass/skip → PASS · 하나라도 fail → FAIL · 계산 불가 다수 → INSUFFICIENT_DATA
    """
    reasons: list[PrincipleReason] = []
    missing: list[str] = []
    result = ScreenerVerdict(verdict="INSUFFICIENT_DATA", reasons=reasons, missing_fields=missing)

    # ─── 원칙 1: PER (트레일링) ─────────────────────────────
    per_ttm_max = float(get_threshold("per", "per_ttm_max"))
    per_op_max = float(get_threshold("per", "per_operating_max"))
    r1 = PrincipleReason(code="per", status="insufficient")
    if inp.market_cap is None:
        missing.append("market_cap")
        r1.note = "market_cap 결측"
    elif inp.net_income_owner_ttm is None:
        missing.append("net_income_owner_ttm")
        r1.note = "net_income_owner_ttm 결측"
    elif inp.net_income_owner_ttm <= 0:
        # v1.0.1 loss_handling
        r1.status = "fail"
        r1.value = {"per_ttm": None, "net_income_owner_ttm": inp.net_income_owner_ttm}
        r1.note = f"지배주주순이익 TTM ≤ 0 ({inp.net_income_owner_ttm:.0f}원) → 자동 fail"
    else:
        per_ttm = inp.market_cap / inp.net_income_owner_ttm
        result.per_ttm = per_ttm
        per_op = None
        if inp.operating_income_ttm and inp.operating_income_ttm > 0:
            per_op = inp.market_cap / inp.operating_income_ttm
            result.per_operating = per_op
        r1.value = {"per_ttm": per_ttm, "per_operating": per_op}
        r1.threshold = {"per_ttm_max": per_ttm_max, "per_operating_max": per_op_max}
        if per_ttm <= per_ttm_max and (per_op is None or per_op <= per_op_max):
            r1.status = "pass"
            r1.note = f"PER TTM {per_ttm:.2f} ≤ {per_ttm_max}" + (
                f" · PER 영업 {per_op:.2f} ≤ {per_op_max}" if per_op else ""
            )
        else:
            r1.status = "fail"
            if per_ttm > per_ttm_max:
                r1.note = f"PER TTM {per_ttm:.2f} > {per_ttm_max}"
            else:
                r1.note = f"PER 영업 {per_op:.2f} > {per_op_max}"
    reasons.append(r1)

    # ─── 원칙 2: 주주환원율 3년 평균 ────────────────────────
    payout_min = float(get_threshold("shareholder_return", "payout_ratio_3y_avg_min"))
    r2 = PrincipleReason(code="shareholder_return", status="insufficient")
    if any(v is None for v in inp.net_income_owner_3y) or len(inp.net_income_owner_3y) < 3:
        missing.append("net_income_owner_3y")
        r2.note = "지배주주순이익 3년 결측"
    elif any(v is None for v in inp.dividend_total_3y) or any(v is None for v in inp.buyback_cashflow_3y):
        missing.append("shareholder_return_3y")
        r2.note = "배당·자기주식 3년 결측"
    else:
        ratios: list[float] = []
        loss_year = False
        for ni, div, buy in zip(
            inp.net_income_owner_3y, inp.dividend_total_3y, inp.buyback_cashflow_3y
        ):
            if ni is None or ni <= 0:
                loss_year = True
                break
            total_return = (div or 0) + (buy or 0)  # buyback 은 caller 가 절대값 저장
            ratios.append(total_return / ni)
        if loss_year:
            # v1.0.1 loss_handling · 3년 중 1개년이라도 fail 이면 원칙 fail
            r2.status = "fail"
            r2.note = "3년 중 적자 연도 있음 (분모 무효) → 자동 fail"
        else:
            avg = sum(ratios) / len(ratios)
            result.payout_ratio_3y_avg = avg
            r2.value = {"ratios": [round(x, 4) for x in ratios], "avg": round(avg, 4)}
            r2.threshold = {"payout_ratio_3y_avg_min": payout_min}
            if avg >= payout_min:
                r2.status = "pass"
                r2.note = f"3년 평균 {avg * 100:.1f}% ≥ {payout_min * 100:.0f}%"
            else:
                r2.status = "fail"
                r2.note = f"3년 평균 {avg * 100:.1f}% < {payout_min * 100:.0f}%"
    reasons.append(r2)

    # ─── 원칙 3: 배당 지속성 5년 · 감배 없음 ───────────────
    years_min = int(get_threshold("dividend_continuity", "consecutive_years_min"))
    cut_allowed = bool(get_threshold("dividend_continuity", "cut_allowed"))
    r3 = PrincipleReason(code="dividend_continuity", status="insufficient")
    dps5 = inp.dividend_per_share_5y
    # v1.0.2 · 5년 미만 (신규상장) 은 INSUFFICIENT 아닌 FAIL(history_short)
    if len(dps5) < years_min or all(v is None for v in dps5):
        # 이력 자체가 없거나 짧음 · 결측이 아니라 이력 짧음 · FAIL
        r3.status = "fail"
        r3.note = f"배당 이력 {len(dps5)}년 < {years_min}년 (history_short)"
        r3.value = {"history_short": True, "years_available": len(dps5)}
        result.dividend_years = len(dps5)
    else:
        # 5년치 모두 존재 · 연속성 + 감배 검증
        recent5 = dps5[-years_min:]
        if any(v is None for v in recent5):
            # 중간 결측 · 데이터 결함
            missing.append("dividend_per_share_5y")
            r3.note = f"배당 이력 최근 {years_min}년 중 결측 존재"
        else:
            zero_count = sum(1 for v in recent5 if v == 0)
            cut_events = 0
            for prev, cur in zip(recent5[:-1], recent5[1:]):
                if cur < prev:
                    cut_events += 1
            result.dividend_years = years_min
            result.dividend_cut = cut_events > 0
            r3.value = {
                "dps_5y": [round(v, 2) if v is not None else None for v in recent5],
                "cut_events": cut_events,
                "zero_count": zero_count,
            }
            r3.threshold = {
                "consecutive_years_min": years_min,
                "cut_allowed": cut_allowed,
            }
            if zero_count > 0:
                r3.status = "fail"
                r3.note = f"최근 {years_min}년 중 무배당 {zero_count}년"
            elif cut_events > 0 and not cut_allowed:
                r3.status = "fail"
                r3.note = f"최근 {years_min}년 중 감배 {cut_events}회"
            else:
                r3.status = "pass"
                r3.note = f"최근 {years_min}년 연속 배당 · 감배 없음"
    reasons.append(r3)

    # ─── 원칙 4: 재무 건전성 (금융업 skip) ─────────────────
    debt_max = float(get_threshold("financial_soundness", "debt_ratio_max"))
    coverage_min = float(get_threshold("financial_soundness", "interest_coverage_min"))
    r4 = PrincipleReason(code="financial_soundness", status="insufficient")
    if inp.is_financial_sector:
        r4.status = "skip"
        r4.note = "금융업 (sector_exception)"
    elif inp.total_liabilities is None or inp.total_equity is None or inp.total_equity <= 0:
        missing.append("balance_sheet")
        r4.note = "부채총계·자본총계 결측 (또는 자본잠식)"
    else:
        debt_ratio = inp.total_liabilities / inp.total_equity
        result.debt_ratio = debt_ratio
        # 이자보상배율 = 영업이익 / 이자비용 · 이자비용 0 이거나 결측 시 pass 처리 (부채 없음 가정)
        ic: Optional[float] = None
        if inp.operating_income_ttm is not None and inp.interest_expense_ttm:
            ic = inp.operating_income_ttm / inp.interest_expense_ttm
            result.interest_coverage = ic
        r4.value = {"debt_ratio": round(debt_ratio, 4), "interest_coverage": ic}
        r4.threshold = {"debt_ratio_max": debt_max, "interest_coverage_min": coverage_min}
        if debt_ratio > debt_max:
            r4.status = "fail"
            r4.note = f"부채비율 {debt_ratio * 100:.1f}% > {debt_max * 100:.0f}%"
        elif ic is not None and ic < coverage_min:
            r4.status = "fail"
            r4.note = f"이자보상배율 {ic:.2f} < {coverage_min}"
        else:
            r4.status = "pass"
            r4.note = f"부채비율 {debt_ratio * 100:.1f}% ≤ {debt_max * 100:.0f}%" + (
                f" · 이자보상배율 {ic:.2f} ≥ {coverage_min}" if ic else " · 이자비용 없음"
            )
    reasons.append(r4)

    # ─── 원칙 5: 분산 규칙 (스크리너 미강제 · 게이트 전용) ─
    r5 = PrincipleReason(
        code="diversification",
        status="skip",
        note="스크리너 결과에는 지표만 표기 · 게이트에서 강제 (charter §5 scope)",
    )
    reasons.append(r5)

    # ─── 종합 판정 ─────────────────────────────────────────
    # skip 은 pass 동일 취급 (해당 원칙 배제)
    # insufficient 가 (P1·P2·P3·P4 중) 1개 이상 있으면 INSUFFICIENT
    # fail 이 1개 이상 있으면 FAIL (INSUFFICIENT 보다 우선 · 계산 가능한 근거로 탈락)
    core_reasons = [r for r in reasons if r.code != "diversification"]
    has_fail = any(r.status == "fail" for r in core_reasons)
    has_insufficient = any(r.status == "insufficient" for r in core_reasons)
    if has_fail:
        result.verdict = "FAIL"
    elif has_insufficient:
        result.verdict = "INSUFFICIENT_DATA"
    else:
        result.verdict = "PASS"

    return result
