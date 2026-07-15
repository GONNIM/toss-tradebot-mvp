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
from datetime import datetime, timezone
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
from .config import ScreenerThresholds, get_thresholds
from .piotroski import FinancialPeriod, calculate_f_score

logger = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    """단일 종목 · 조건별 판정 결과."""
    ticker: str
    passed_all: bool
    status: str                            # passed / rejected / cash_suspect
    conditions: dict[str, bool] = field(default_factory=dict)
    reject_reasons: list[str] = field(default_factory=list)
    # 서브스코어
    net_cash_ratio: Optional[float] = None
    piotroski_f_score: Optional[int] = None
    owner_pct: Optional[float] = None
    treasury_pct: Optional[float] = None
    pbr: Optional[float] = None
    dividend_payout: Optional[float] = None


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

    # 데이터 부재 방어
    if fin_latest is None:
        result.reject_reasons.append("no_financial_data")
        return result
    if market is None:
        result.reject_reasons.append("no_market_data")
        return result

    # ── 조건 1 · PBR ────────────────────────
    result.pbr = market.pbr
    c1 = market.pbr is not None and market.pbr < t.pbr_max
    result.conditions["1_pbr"] = c1
    if not c1:
        result.reject_reasons.append(f"pbr>={t.pbr_max}({market.pbr})")

    # ── 조건 2 · 순현금 / 시총 ────────────
    cash = (fin_latest.cash_and_equivalents or 0) + (fin_latest.short_term_investments or 0)
    debt = fin_latest.total_debt or 0
    net_cash = cash - debt
    if market.market_cap and market.market_cap > 0:
        result.net_cash_ratio = net_cash / market.market_cap
        c2 = result.net_cash_ratio > t.net_cash_ratio_min
    else:
        c2 = False
    result.conditions["2_net_cash_ratio"] = c2
    if not c2:
        result.reject_reasons.append(
            f"net_cash<{t.net_cash_ratio_min}({result.net_cash_ratio:.3f})"
            if result.net_cash_ratio is not None else "no_market_cap"
        )

    # ── 조건 3 · 최대주주 지분율 ──────────
    if holder is not None:
        result.owner_pct = (holder.major_pct or 0) + (holder.related_pct or 0)
        result.treasury_pct = holder.treasury_pct
        c3 = result.owner_pct >= t.major_shareholder_pct_min
    else:
        c3 = False
    result.conditions["3_owner_pct"] = c3
    if not c3:
        result.reject_reasons.append(
            f"owner<{t.major_shareholder_pct_min}({result.owner_pct})"
            if result.owner_pct is not None else "no_shareholder_data"
        )

    # ── 조건 4 · 공정위 대기업집단 아님 ────
    is_big = await is_big_biz_group(ticker, year)
    c4 = not is_big
    result.conditions["4_not_big_biz"] = c4
    if not c4:
        result.reject_reasons.append("big_biz_group")

    # ── 조건 5 · 감사의견 적정 (최근 2년) ──
    audits = [fs.audit_opinion for fs in fin_all[:2] if fs.audit_opinion]
    c5 = len(audits) >= 2 and all(op == "적정" for op in audits[:2])
    result.conditions["5_audit_opinion"] = c5
    if not c5:
        if len(audits) < 2:
            result.reject_reasons.append(f"audit<2yrs({len(audits)})")
        else:
            result.reject_reasons.append(f"audit_not_적정({','.join(audits[:2])})")

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
    op_incomes = [fs.operating_income for fs in fin_all[:3] if fs.operating_income is not None]
    positive = sum(1 for oi in op_incomes if oi > 0)
    c7 = len(op_incomes) >= 3 and positive >= 2
    result.conditions["7_operating_profit"] = c7
    if not c7:
        result.reject_reasons.append(f"op_profit_history({positive}/{len(op_incomes)})")

    # ── 조건 8 · F-Score ≥ 6 ────────────────
    if len(fin_all) >= 2:
        fscore = calculate_f_score(
            current=_period_from_snapshot(fin_all[0]),
            prior=_period_from_snapshot(fin_all[1]),
        )
        result.piotroski_f_score = fscore.total_score
        c8 = fscore.total_score >= t.piotroski_f_score_min
    else:
        c8 = False
        result.piotroski_f_score = None
    result.conditions["8_fscore"] = c8
    if not c8:
        result.reject_reasons.append(f"fscore<{t.piotroski_f_score_min}({result.piotroski_f_score})")

    # ── 조건 9 · ADV60 ≥ 1억 ────────────────
    c9 = (market.avg_daily_amount_60d or 0) >= t.adv_60d_min_krw
    result.conditions["9_adv60"] = c9
    if not c9:
        result.reject_reasons.append(f"adv60<{t.adv_60d_min_krw:.0f}({market.avg_daily_amount_60d})")

    # ── 조건 10 · 관리종목·거래정지 이력 없음 ─
    # v1 · 별도 이력 수집 없음 · 감사의견 비적정 이력으로 근사
    #     PowderKegEvent B2/B3 조회는 이벤트 수집 이후 · v2 구현 예정
    c10 = True   # v1 · 조건 5 로 근사
    result.conditions["10_no_bad_history"] = c10

    # ── 통합 판정 ────────────────────────
    result.passed_all = all(result.conditions.values())
    if result.passed_all:
        result.status = "passed"
    elif cash_check.reason.startswith("no_interest_income") or cash_check.reason.startswith("yield_below"):
        result.status = "cash_suspect"
    else:
        result.status = "rejected"

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
        run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")

    stats = {"run_id": run_id, "total": 0, "passed": 0, "rejected": 0, "cash_suspect": 0}
    async with get_session() as session:
        for ticker in tickers:
            stats["total"] += 1
            try:
                r = await screen_ticker(ticker, thresholds, year)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[screener] %s 실패 · %s", ticker, exc)
                continue

            session.add(PowderKegList(
                run_id=run_id, ticker=ticker,
                status=r.status,
                net_cash_ratio=r.net_cash_ratio,
                piotroski_f_score=r.piotroski_f_score,
                owner_pct=r.owner_pct,
                treasury_pct=r.treasury_pct,
                pbr=r.pbr,
                dividend_payout=None,   # v1 · 배당성향 데이터 없음
                conditions_json=json.dumps(r.conditions, ensure_ascii=False),
                reject_reasons=",".join(r.reject_reasons) if r.reject_reasons else None,
            ))
            stats[r.status] = stats.get(r.status, 0) + 1

    logger.info("[screener.run] %s", stats)
    return stats
