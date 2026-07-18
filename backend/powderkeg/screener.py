"""화약고 스크리너 · Phase 7-2 오케스트레이터.

10 조건 (§7-2 표):
    1  PBR < 0.5
    2  순현금(현금+단기금융상품 - 총차입금) / 시가총액 > 40%
    3  최대주주+특수관계인 지분율 ≥ 40%
    4  공정위 공시대상기업집단 소속 아님
    5  감사의견 적정 (최근 2개 연도)
    6  이자수익 교차검증 (verify_cash_reality)
    7  영업이익 최근 3년 중 2년 이상 흑자
    8  피오트로스키 F-Score ≥ 6
    9  60일 일평균 거래대금 ≥ 1억
    10 관리종목/거래정지/감사비적정 이력 3년 없음

결과: PowderKegList 테이블 (run_id 별 히스토리 유지 · status=passed/rejected/cash_suspect).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import (
    FinancialSnapshot,
    KrxMarketSnapshot,
    MajorShareholder,
    PowderKegList,
)

from .cash_verifier import verify_cash_reality
from .collectors.ftc_big_biz import is_big_biz_group
from .collectors.order_industry_seed import (
    is_order_industry, order_industry_info,
    is_financial_industry, financial_industry_info,
    should_apply_contract_liab_adjustment,
)
from .config import ScreenerThresholds, get_thresholds
from .piotroski import FinancialPeriod, calculate_f_score

logger = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    """단일 종목 · 조건별 판정 결과."""
    ticker: str
    passed_all: bool
    status: str                            # passed / rejected / cash_suspect
    name: Optional[str] = None             # KRX/유니버스 이름
    conditions: dict[str, bool] = field(default_factory=dict)
    reject_reasons: list[str] = field(default_factory=list)
    # 서브스코어
    net_cash_ratio: Optional[float] = None            # 조건 2 판정 근거 (수주산업이면 조정 값)
    net_cash_ratio_raw: Optional[float] = None        # v1.30 · P2 · 원 값 (계약부채 미차감) UI 병기용
    net_cash_ratio_adj: Optional[float] = None        # v1.30 · P2 · 조정 값 (수주산업만 산출)
    order_industry_sector: Optional[str] = None       # v1.30 · P2 · "건설"/"조선"/"플랜트" or None
    piotroski_f_score: Optional[int] = None
    owner_pct: Optional[float] = None
    treasury_pct: Optional[float] = None
    pbr: Optional[float] = None
    dividend_payout: Optional[float] = None
    # v1.14 · 강건성 (리뷰어 지적 #5)
    robustness_score: Optional[float] = None    # 0.0 ~ 1.0 · min margin 정규화
    robustness_grade: Optional[str] = None      # strong / moderate / borderline / at_risk
    condition_margins: dict[str, float] = field(default_factory=dict)   # 조건별 임계 대비 여유


def _compute_robustness(
    conditions_passed: dict[str, bool],
    thresholds,
    pbr: Optional[float],
    net_cash_ratio: Optional[float],
    owner_pct: Optional[float],
    piotroski_f_score: Optional[int],
) -> tuple[Optional[float], Optional[str], dict[str, float]]:
    """조건별 임계 여유 계산 · 최소 margin = robustness_score.

    v1.14 (리뷰어 지적 #5): 서희건설 · PBR 0.476 (임계 0.5) · net_cash 40.6% (임계 40%)
      경계선 통과 · 시총 1.5% 변동 시 탈락 · 강건성 명시 필요.

    Margin 정의 (모두 정규화):
      · c1 pbr < 0.5      → (0.5 - pbr) / 0.5
      · c2 net_cash > 40% → (net_cash - 0.4) / 0.4
      · c3 owner >= 40%   → (owner - 0.4) / 0.4
      · c8 fscore >= 6    → (fscore - 6) / 6

    Grade (min margin 기준):
      · ≥ 0.20 · strong     🟢
      · ≥ 0.10 · moderate   🟡
      · ≥ 0.05 · borderline 🟠
      · <  0.05 · at_risk   🔴
    """
    margins: dict[str, float] = {}
    if pbr is not None and pbr > 0:
        margins["1_pbr"] = round((thresholds.pbr_max - pbr) / thresholds.pbr_max, 4)
    if net_cash_ratio is not None:
        margins["2_net_cash"] = round((net_cash_ratio - thresholds.net_cash_ratio_min) / thresholds.net_cash_ratio_min, 4)
    if owner_pct is not None:
        margins["3_owner"] = round((owner_pct - thresholds.major_shareholder_pct_min) / thresholds.major_shareholder_pct_min, 4)
    if piotroski_f_score is not None:
        margins["8_fscore"] = round((piotroski_f_score - thresholds.piotroski_f_score_min) / thresholds.piotroski_f_score_min, 4)

    if not margins:
        return None, None, {}

    # passed_all=True 상태에서만 의미 있음 · rejected 는 음수 margin
    positive_margins = [m for m in margins.values() if m >= 0]
    if not positive_margins:
        return None, None, margins
    score = min(positive_margins)

    if score >= 0.20:
        grade = "strong"
    elif score >= 0.10:
        grade = "moderate"
    elif score >= 0.05:
        grade = "borderline"
    else:
        grade = "at_risk"

    return score, grade, margins


async def _latest_financial(ticker: str, report_code: str = "11011") -> Optional[FinancialSnapshot]:
    """가장 최신 (release_date 기준) 사업보고서 스냅샷."""
    async with get_session() as session:
        stmt = (
            select(FinancialSnapshot)
            .where(FinancialSnapshot.ticker == ticker, FinancialSnapshot.report_code == report_code)
            .order_by(FinancialSnapshot.reference_date.desc(), FinancialSnapshot.release_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def _all_financials(ticker: str, report_code: str = "11011") -> list[FinancialSnapshot]:
    """전체 사업보고서 스냅샷 · reference_date 내림차순."""
    async with get_session() as session:
        stmt = (
            select(FinancialSnapshot)
            .where(FinancialSnapshot.ticker == ticker, FinancialSnapshot.report_code == report_code)
            .order_by(FinancialSnapshot.reference_date.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def _latest_market(ticker: str) -> Optional[KrxMarketSnapshot]:
    async with get_session() as session:
        stmt = (
            select(KrxMarketSnapshot)
            .where(KrxMarketSnapshot.ticker == ticker)
            .order_by(KrxMarketSnapshot.snapshot_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def _resolve_name(ticker: str) -> Optional[str]:
    """종목명 해결 순서: KrxMarketSnapshot (최신) → LiveTapeUniverse (KOSDAQ) → None."""
    from backend.services.models import LiveTapeUniverse
    async with get_session() as session:
        # 1. KRX 스냅샷 (전 KOSPI+KOSDAQ 2700+ 종목)
        stmt = (
            select(KrxMarketSnapshot.name)
            .where(KrxMarketSnapshot.ticker == ticker, KrxMarketSnapshot.name.is_not(None))
            .order_by(KrxMarketSnapshot.snapshot_date.desc())
            .limit(1)
        )
        n = (await session.execute(stmt)).scalar_one_or_none()
        if n:
            return n
        # 2. Sniper LiveTape KOSDAQ 유니버스 fallback
        stmt = select(LiveTapeUniverse.name).where(LiveTapeUniverse.ticker == ticker).limit(1)
        n = (await session.execute(stmt)).scalar_one_or_none()
        if n:
            return n
    return None


async def _latest_shareholder(ticker: str) -> Optional[MajorShareholder]:
    async with get_session() as session:
        stmt = (
            select(MajorShareholder)
            .where(MajorShareholder.ticker == ticker)
            .order_by(MajorShareholder.reference_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def screen_ticker(
    ticker: str,
    thresholds: Optional[ScreenerThresholds] = None,
    year: int = 2026,
) -> ScreenResult:
    """단일 종목 · 10 조건 판정."""
    t = thresholds or get_thresholds()
    result = ScreenResult(ticker=ticker, passed_all=False, status="rejected")

    fin_latest = await _latest_financial(ticker)
    fin_all = await _all_financials(ticker)
    market = await _latest_market(ticker)
    holder = await _latest_shareholder(ticker)
    result.name = await _resolve_name(ticker)

    # 데이터 부재 방어
    if fin_latest is None:
        result.reject_reasons.append("no_financial_data")
        return result
    if market is None:
        result.reject_reasons.append("no_market_data")
        return result

    # ── 조건 1 · PBR (KRX 값 우선 · None 이면 자체 계산 fallback) ─
    #    FDR StockListing 은 PBR 미제공 (KOSPI/KOSDAQ 전체) · book value 로 계산.
    #    v1.29 · 3차 리뷰 P1 · 데이터 부족(None) 과 실 실패(False) 분리.
    pbr_effective = market.pbr
    if pbr_effective is None and fin_latest.total_equity and market.market_cap:
        if fin_latest.total_equity > 0:
            pbr_effective = market.market_cap / fin_latest.total_equity
    result.pbr = pbr_effective
    if pbr_effective is None:
        c1 = None
        result.reject_reasons.append("pbr:no_data")
    else:
        c1 = pbr_effective < t.pbr_max
        if not c1:
            result.reject_reasons.append(f"pbr>={t.pbr_max}({pbr_effective})")
    result.conditions["1_pbr"] = c1

    # ── 조건 2 · 순현금 / 시총 ────────────
    # v1.30 · 3차 리뷰 P2 · 수주산업 계약부채 조정
    #   조정 순현금 = cash - total_debt - contract_liabilities
    # v1.33 · 3차 리뷰 P2-4e (2026-07-18):
    #   판별 우선순위 · 금융업(스킵) > 명시 시드 > 자동(cl/mcap > 3%)
    cash = (fin_latest.cash_and_equivalents or 0) + (fin_latest.short_term_investments or 0)
    debt = fin_latest.total_debt or 0
    contract_liab = fin_latest.contract_liabilities or 0
    net_cash_raw = cash - debt

    apply_adj = should_apply_contract_liab_adjustment(ticker, contract_liab, market.market_cap or 0)
    if apply_adj:
        # sector 라벨 · 명시 시드 우선, 없으면 "자동"
        oi = order_industry_info(ticker)
        result.order_industry_sector = oi[1] if oi else "자동(cl>3%)"
        net_cash_adj = cash - debt - contract_liab
        net_cash_effective = net_cash_adj
    else:
        net_cash_adj = None
        net_cash_effective = net_cash_raw
        # 금융업 태그 (UI 참고)
        if is_financial_industry(ticker):
            fi = financial_industry_info(ticker)
            result.order_industry_sector = f"금융({fi[1]})" if fi else "금융"

    if market.market_cap and market.market_cap > 0:
        result.net_cash_ratio_raw = net_cash_raw / market.market_cap
        if net_cash_adj is not None:
            result.net_cash_ratio_adj = net_cash_adj / market.market_cap
        result.net_cash_ratio = net_cash_effective / market.market_cap
        c2 = result.net_cash_ratio > t.net_cash_ratio_min
        if not c2:
            if apply_adj:
                result.reject_reasons.append(
                    f"net_cash_adj<{t.net_cash_ratio_min}({result.net_cash_ratio:.3f})"
                    f" · raw={result.net_cash_ratio_raw:.3f} · contract_liab={contract_liab:,.0f}"
                    f" · sector={result.order_industry_sector}"
                )
            else:
                result.reject_reasons.append(f"net_cash<{t.net_cash_ratio_min}({result.net_cash_ratio:.3f})")
    else:
        c2 = None
        result.reject_reasons.append("net_cash:no_market_cap")
    result.conditions["2_net_cash_ratio"] = c2

    # ── 조건 3 · 최대주주 지분율 ──────────
    if holder is not None:
        result.owner_pct = (holder.major_pct or 0) + (holder.related_pct or 0)
        result.treasury_pct = holder.treasury_pct
        c3 = result.owner_pct >= t.major_shareholder_pct_min
        if not c3:
            result.reject_reasons.append(f"owner<{t.major_shareholder_pct_min}({result.owner_pct})")
    else:
        c3 = None
        result.reject_reasons.append("owner:no_shareholder_data")
    result.conditions["3_owner_pct"] = c3

    # ── 조건 4 · 공정위 대기업집단 아님 ────
    is_big = await is_big_biz_group(ticker, year)
    c4 = not is_big
    result.conditions["4_not_big_biz"] = c4
    if not c4:
        result.reject_reasons.append("big_biz_group")

    # ── 조건 5 · 감사의견 적정 (최근 2년) ──
    #    DART 실 응답 · "적정의견" 반환 · substring 매치 (한정/부적정 명시 포함 방지).
    audits = [fs.audit_opinion for fs in fin_all[:2] if fs.audit_opinion]
    def _is_적정(op: str) -> bool:
        op = (op or "").strip()
        if not op:
            return False
        if any(bad in op for bad in ("한정", "부적정", "의견거절")):
            return False
        return "적정" in op   # "적정의견" · "적정" 모두 포함
    # v1.29 · 3차 리뷰 P1 · 데이터 <2년(None) 과 부적정(False) 분리.
    if len(audits) < 2:
        c5 = None
        result.reject_reasons.append(f"audit:no_data<2yrs({len(audits)})")
    else:
        c5 = all(_is_적정(op) for op in audits[:2])
        if not c5:
            result.reject_reasons.append(f"audit_not_적정({','.join(audits[:2])})")
    result.conditions["5_audit_opinion"] = c5

    # ── 조건 6 · 이자수익 교차검증 (cash_suspect) ─
    cash_prior = None
    if len(fin_all) >= 2:
        cash_prior = (fin_all[1].cash_and_equivalents or 0) + (fin_all[1].short_term_investments or 0)
    cash_check = verify_cash_reality(
        interest_income=fin_latest.interest_income,
        cash_current=cash if cash > 0 else None,
        cash_prior=cash_prior if cash_prior and cash_prior > 0 else None,
        base_rate=t.boK_base_rate, margin=t.interest_income_yield_margin,
    )
    c6 = cash_check.passed
    result.conditions["6_cash_reality"] = c6
    if not c6:
        result.reject_reasons.append(f"cash_suspect:{cash_check.reason}")

    # ── 조건 7 · 영업이익 3년 중 2년 흑자 ─
    # v1.29 · 3차 리뷰 P1 · 데이터 <3년(None) 과 흑자 <2년(False) 분리.
    op_incomes = [fs.operating_income for fs in fin_all[:3] if fs.operating_income is not None]
    positive = sum(1 for oi in op_incomes if oi > 0)
    if len(op_incomes) < 3:
        c7 = None
        result.reject_reasons.append(f"op_profit:no_data<3yrs({len(op_incomes)})")
    else:
        c7 = positive >= 2
        if not c7:
            result.reject_reasons.append(f"op_profit_history({positive}/{len(op_incomes)})")
    result.conditions["7_operating_profit"] = c7

    # ── 조건 8 · F-Score ≥ 6 ────────────────
    # v1.29 · 3차 리뷰 P1 · 데이터 <2년(None) 과 F-Score < 임계(False) 분리.
    if len(fin_all) >= 2:
        fscore = calculate_f_score(
            current=_period_from_snapshot(fin_all[0]),
            prior=_period_from_snapshot(fin_all[1]),
        )
        result.piotroski_f_score = fscore.total_score
        c8 = fscore.total_score >= t.piotroski_f_score_min
        if not c8:
            result.reject_reasons.append(f"fscore<{t.piotroski_f_score_min}({result.piotroski_f_score})")
    else:
        c8 = None
        result.piotroski_f_score = None
        result.reject_reasons.append(f"fscore:no_data<2yrs({len(fin_all)})")
    result.conditions["8_fscore"] = c8

    # ── 조건 9 · ADV60 ≥ 1억 ────────────────
    # v1.29 · 3차 리뷰 P1 · KRX 데이터 부재(None) 와 실 <임계(False) 분리.
    if market.avg_daily_amount_60d is None:
        c9 = None
        result.reject_reasons.append("adv60:no_data")
    else:
        c9 = market.avg_daily_amount_60d >= t.adv_60d_min_krw
        if not c9:
            result.reject_reasons.append(f"adv60<{t.adv_60d_min_krw:.0f}({market.avg_daily_amount_60d})")
    result.conditions["9_adv60"] = c9

    # ── 조건 10 · 관리종목·거래정지 이력 없음 ─
    # v1 · 별도 이력 수집 없음 · 감사의견 비적정 이력으로 근사
    #     PowderKegEvent B2/B3 조회는 이벤트 수집 이후 · v2 구현 예정
    c10 = True   # v1 · 조건 5 로 근사
    result.conditions["10_no_bad_history"] = c10

    # ── 통합 판정 ────────────────────────
    # v1.29 · 3차 리뷰 P1 · 명시적 True 체크 (None 은 데이터 부족 · passed 자격 없음).
    result.passed_all = all(v is True for v in result.conditions.values())
    if result.passed_all:
        result.status = "passed"
    elif cash_check.reason.startswith("no_interest_income") or cash_check.reason.startswith("yield_below"):
        result.status = "cash_suspect"
    else:
        result.status = "rejected"

    # v1.14 · 강건성 스코어 (리뷰어 지적 #5)
    score, grade, margins = _compute_robustness(
        conditions_passed=result.conditions,
        thresholds=t,
        pbr=result.pbr,
        net_cash_ratio=result.net_cash_ratio,
        owner_pct=result.owner_pct,
        piotroski_f_score=result.piotroski_f_score,
    )
    result.robustness_score = score
    result.robustness_grade = grade
    result.condition_margins = margins

    return result


def _period_from_snapshot(fs: FinancialSnapshot) -> FinancialPeriod:
    return FinancialPeriod(
        net_income=fs.net_income,
        cash_flow_from_operations=fs.cash_flow_from_operations,
        total_assets=fs.total_assets,
        total_debt=fs.total_debt,
        current_assets=fs.current_assets,
        current_liabilities=fs.current_liabilities,
        revenue=fs.revenue,
        gross_profit=fs.gross_profit,
        shares_outstanding=fs.shares_outstanding,
    )


async def run_screener(
    tickers: Iterable[str],
    thresholds: Optional[ScreenerThresholds] = None,
    year: int = 2026,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """유니버스 순회 · PowderKegList upsert.

    Returns: {"run_id", "total", "passed", "rejected", "cash_suspect"}
    """
    if run_id is None:
        # v1.15 · KST 시간 (Asia/Seoul UTC+9) 명시 · UI 표시 정합
        _kst = timezone(timedelta(hours=9))
        run_id = datetime.now(tz=_kst).strftime("%Y%m%d-%H%M%SK")

    # locked=True 인 종목 union · 사용자가 lock 걸어둔 종목은 유니버스에 없어도 항상 재평가
    #   (스케줄러 자동 실행에서도 수동 추가 종목이 orphan 안 되도록 보장)
    # v1.17 (버그 fix): 이전 · 모든 run 의 locked=True 검색 → 삭제 후에도 재승격 발생.
    #                   지금 · 최신 run 의 locked=True 만 참조 · 삭제 흔적은 배제.
    input_set = list(dict.fromkeys(tickers))   # dedupe · 순서 유지
    async with get_session() as session:
        latest_run = (await session.execute(
            select(PowderKegList.run_id).order_by(PowderKegList.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        locked_tickers: list[str] = []
        if latest_run is not None:
            locked_tickers = list((await session.execute(
                select(PowderKegList.ticker).where(
                    PowderKegList.run_id == latest_run,
                    PowderKegList.locked == True,   # noqa: E712
                ).distinct()
            )).scalars().all())
    extra = [t for t in locked_tickers if t not in input_set]
    if extra:
        logger.info(
            "[screener.run] locked union (latest run %s) · %d extra tickers: %s",
            latest_run, len(extra), extra,
        )
        input_set = input_set + extra

    stats = {"run_id": run_id, "total": 0, "passed": 0, "rejected": 0, "cash_suspect": 0}
    async with get_session() as session:
        for ticker in input_set:
            stats["total"] += 1
            try:
                r = await screen_ticker(ticker, thresholds, year)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[screener] %s 실패 · %s", ticker, exc)
                continue

            # locked 상태 유지 · 이전 run 에서 사용자가 lock 한 종목은 lock 유지·added_by=user 보존
            prev_locked = (await session.execute(
                select(PowderKegList).where(
                    PowderKegList.ticker == ticker,
                    PowderKegList.locked == True,   # noqa: E712
                ).limit(1)
            )).scalar_one_or_none()
            # v1.14 · conditions_json 에 robustness meta 병기
            conditions_with_meta = dict(r.conditions)
            conditions_with_meta["_robustness"] = {
                "score": r.robustness_score,
                "grade": r.robustness_grade,
                "margins": r.condition_margins,
            }
            session.add(PowderKegList(
                run_id=run_id, ticker=ticker,
                name=r.name,
                status=r.status,
                net_cash_ratio=r.net_cash_ratio,
                piotroski_f_score=r.piotroski_f_score,
                owner_pct=r.owner_pct,
                treasury_pct=r.treasury_pct,
                pbr=r.pbr,
                dividend_payout=None,   # v1 · 배당성향 데이터 없음
                conditions_json=json.dumps(conditions_with_meta, ensure_ascii=False),
                reject_reasons=",".join(r.reject_reasons) if r.reject_reasons else None,
                locked=bool(prev_locked),
                added_by=prev_locked.added_by if prev_locked else "auto",
                user_note=prev_locked.user_note if prev_locked else None,
            ))
            stats[r.status] = stats.get(r.status, 0) + 1

    logger.info("[screener.run] %s", stats)
    return stats
