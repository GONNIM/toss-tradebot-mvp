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
    # 2026-08-18 신설 · TTM sanity check 참조 (사업보고서 연간 지배주주순이익)
    latest_annual_net_income_owner: Optional[float] = None
    # v1.0.6-rev3 (2026-08-19) · sanity check 재설계 참조 필드
    q_yoy: Optional[float] = None                    # 최신 분기 vs 전년 동기 누적 (감사 원값)
    q_yoy_base_current: Optional[float] = None
    q_yoy_base_prev: Optional[float] = None
    q_yoy_fail_reason: Optional[str] = None          # yoy_base_missing / yoy_base_invalid
    net_income_source_account: Optional[str] = None  # 파서 매칭 계정 (이후 수집분만)
    # v1.0.7 (2026-08-21) · cum_fallback (add 부재로 thstrm 사용) 발생 필드 · TTM 경로
    # 사용 시 reasons 에 cum_fallback_unverified 기록 (정합성 미검증 표시).
    cum_fallback_fields: list[str] = field(default_factory=list)


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

    # v1.0.7 (2026-08-21) · cum_fallback_unverified · TTM 경로 필드 fallback 발생 시 기록.
    # 정합성 미검증 표시 · 판정에 영향 없음 (warn) · 원문 대조로 후속 검증 필요.
    _TTM_FIELDS = {"net_income_owner_cum", "operating_income_cum", "interest_expense_cum"}
    if inp.cum_fallback_fields:
        used_fallback = sorted(f for f in inp.cum_fallback_fields if f in _TTM_FIELDS)
        if used_fallback:
            reasons.append(PrincipleReason(
                code="cum_fallback_unverified", status="warn",
                value={"fields": used_fallback},
                note=(
                    f"cum_fallback_unverified · thstrm_add 부재로 thstrm_amount fallback · "
                    f"{', '.join(used_fallback)} · 정합성 미검증 · 원문 대조 권장"
                ),
            ))

    # ─── Sanity check v1.0.6-rev3 · 2단 검증 (계정 → YoY) ────────────
    # 사용자 rev3 조건부 승인 (2026-08-19):
    #   1차 · 계정 검증 (source_account whitelist) OR heuristic (capital_ratio > 0.80)
    #   2차 · YoY 검증 · TTM vs 연간 [0.5, 2.0] 초과 시 · Q YoY 원값으로 verified/invalid 판정
    #   자본잠식 (equity <= 0) skip · equity_nonpositive 기록
    if inp.total_equity is not None and inp.total_equity <= 0:
        reasons.append(PrincipleReason(
            code="ttm_sanity", status="skip",
            note="equity_nonpositive · 자본잠식 or 결측 · sanity skip (P4 자연 fail 예상)",
        ))
    else:
        # 1차 · 계정 검증
        _ALLOWED_ACCOUNT_IDS = ("ifrs-full_ProfitLossAttributableToOwnersOfParent",)
        _ALLOWED_ACCOUNT_NM_SUB = (
            "지배기업의 소유주에게 귀속되는 당기순이익",
            "지배기업 소유주지분",
            "지배회사지분",
        )
        if inp.net_income_source_account:
            src = inp.net_income_source_account
            if src not in _ALLOWED_ACCOUNT_IDS and not any(
                nm in src for nm in _ALLOWED_ACCOUNT_NM_SUB
            ):
                reasons.append(PrincipleReason(
                    code="ttm_sanity", status="insufficient",
                    value={"source_account": src},
                    note=f"account_mismatch · '{src[:60]}' 허용 계정 아님",
                ))
                missing.append("ttm_sanity")
                result.verdict = "INSUFFICIENT_DATA"
                return result
        elif (inp.net_income_owner_ttm is not None
              and inp.total_equity is not None and inp.total_equity > 0):
            capital_ratio = abs(inp.net_income_owner_ttm) / abs(inp.total_equity)
            if capital_ratio > 0.80:  # 실 오염 케이스 (삼전 1.11) 감지 · 초호황 (ROE ~30%) 통과
                reasons.append(PrincipleReason(
                    code="ttm_sanity", status="insufficient",
                    value={"capital_ratio": round(capital_ratio, 3)},
                    note=f"account_mismatch_suspected · TTM/자본 비율 {capital_ratio:.2f} > 0.80",
                ))
                missing.append("ttm_sanity")
                result.verdict = "INSUFFICIENT_DATA"
                return result

        # 2차 · YoY 검증 (TTM vs 연간 대비 급변동 시)
        if (inp.net_income_owner_ttm is not None
            and inp.latest_annual_net_income_owner is not None
            and inp.latest_annual_net_income_owner != 0):
            ratio = inp.net_income_owner_ttm / inp.latest_annual_net_income_owner
            if abs(ratio) > 2.0 or abs(ratio) < 0.5:
                # YoY 판정
                if inp.q_yoy is None:
                    # sub-reason 분리 · missing vs invalid
                    fail_reason = inp.q_yoy_fail_reason or "yoy_base_missing"
                    reasons.append(PrincipleReason(
                        code="ttm_sanity", status="insufficient",
                        value={
                            "ratio": round(ratio, 3),
                            "yoy_base_current": inp.q_yoy_base_current,
                            "yoy_base_prev": inp.q_yoy_base_prev,
                        },
                        note=f"{fail_reason} · ratio {ratio:.2f} · Q YoY 판정 불가",
                    ))
                    missing.append("ttm_sanity")
                    result.verdict = "INSUFFICIENT_DATA"
                    return result
                elif inp.q_yoy > 0.50:
                    reasons.append(PrincipleReason(
                        code="ttm_sanity", status="pass",
                        value={
                            "q_yoy": round(inp.q_yoy, 3),
                            "ratio": round(ratio, 3),
                            "yoy_base_current": inp.q_yoy_base_current,
                            "yoy_base_prev": inp.q_yoy_base_prev,
                        },
                        note=f"ttm_surge_verified · Q YoY +{inp.q_yoy*100:.0f}% · ratio {ratio:.2f}",
                    ))
                elif inp.q_yoy < -0.33:
                    reasons.append(PrincipleReason(
                        code="ttm_sanity", status="pass",
                        value={
                            "q_yoy": round(inp.q_yoy, 3),
                            "ratio": round(ratio, 3),
                            "yoy_base_current": inp.q_yoy_base_current,
                            "yoy_base_prev": inp.q_yoy_base_prev,
                        },
                        note=f"ttm_decline_verified · Q YoY {inp.q_yoy*100:.0f}% · ratio {ratio:.2f}",
                    ))
                else:
                    # 급변동 아닌데 ratio 초과 · 데이터 이상 (계절성? 특별 손익?)
                    reasons.append(PrincipleReason(
                        code="ttm_sanity", status="insufficient",
                        value={"ratio": round(ratio, 3), "q_yoy": round(inp.q_yoy, 3)},
                        note=f"ttm_sanity_fail · ratio {ratio:.2f} · Q YoY {inp.q_yoy*100:.0f}% (surge/decline 미달)",
                    ))
                    missing.append("ttm_sanity")
                    result.verdict = "INSUFFICIENT_DATA"
                    return result

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
    # v1.0.5 (2026-08-19 · 이슈 C):
    #   - 배당총액: DART alotMatter 공시 총액 (우선주 포함)
    #   - buyback 결측 = 0 처리 (보수 방향 · "buyback_missing_as_zero" 기록)
    payout_min = float(get_threshold("shareholder_return", "payout_ratio_3y_avg_min"))
    r2 = PrincipleReason(code="shareholder_return", status="insufficient")
    buyback_missing_count = 0
    if any(v is None for v in inp.net_income_owner_3y) or len(inp.net_income_owner_3y) < 3:
        missing.append("net_income_owner_3y")
        r2.note = "지배주주순이익 3년 결측"
    elif any(v is None for v in inp.dividend_total_3y):
        # 배당총액이 3년 중 하나라도 None → 결측 (0 은 확정 무배당 · 통과)
        missing.append("dividend_total_3y")
        r2.note = "배당총액 3년 결측"
    else:
        ratios: list[float] = []
        loss_year = False
        for ni, div, buy in zip(
            inp.net_income_owner_3y, inp.dividend_total_3y, inp.buyback_cashflow_3y
        ):
            if ni is None or ni <= 0:
                loss_year = True
                break
            # v1.0.5 · buyback 결측 = 0 처리 (보수 방향 · payout 낮게 산출)
            if buy is None:
                buyback_missing_count += 1
                buy_val = 0.0
            else:
                buy_val = buy
            total_return = (div or 0) + buy_val
            ratios.append(total_return / ni)
        if loss_year:
            # v1.0.1 loss_handling · 3년 중 1개년이라도 fail 이면 원칙 fail
            r2.status = "fail"
            r2.note = "3년 중 적자 연도 있음 (분모 무효) → 자동 fail"
        else:
            avg = sum(ratios) / len(ratios)
            result.payout_ratio_3y_avg = avg
            r2.value = {
                "ratios": [round(x, 4) for x in ratios],
                "avg": round(avg, 4),
                "buyback_missing_years": buyback_missing_count,
            }
            r2.threshold = {"payout_ratio_3y_avg_min": payout_min}
            buyback_note = (
                f" · buyback_missing_as_zero: {buyback_missing_count}년" if buyback_missing_count else ""
            )
            if avg >= payout_min:
                r2.status = "pass"
                r2.note = f"3년 평균 {avg * 100:.1f}% ≥ {payout_min * 100:.0f}%{buyback_note}"
            else:
                r2.status = "fail"
                r2.note = f"3년 평균 {avg * 100:.1f}% < {payout_min * 100:.0f}%{buyback_note}"
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
