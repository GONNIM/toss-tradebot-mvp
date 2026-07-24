"""화약고 백테스트 · Phase 7-4 오케스트레이터 + validated 게이트.

지시서 §7-4 완료 기준:
    - 이벤트 타입별 CAR 리포트 생성.
    - validated 승격 게이트가 코드로 강제된다.

승격 조건 (하드코딩 · config 화 v2):
    - 표본 ≥ 50 건
    - t-stat > 2.0 (특정 window)
    - 승률 > 50%
    - mean_return > 0 (비용 차감 후 유의미)

validated 승격:
    PowderKegEvent.validated = True (event_type 단위) — 이후 반자동 티켓 (§7-5) 대상.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select, update

from backend.services.db import get_session
from backend.services.models import (
    FinancialSnapshot,
    MajorShareholder,
    PowderKegBacktestReport,
    PowderKegEvent,
)

from .cash_verifier import verify_cash_reality
from .collectors.ftc_big_biz import is_big_biz_group
from .event_study import (
    WINDOW_DAYS,
    AggregatedResult,
    SingleEventReturn,
    aggregate_returns,
    compute_event_return,
)
from .piotroski import FinancialPeriod, calculate_f_score

logger = logging.getLogger(__name__)


# ─── 승격 게이트 임계값 (지시서 §7-4 · v1 하드) ──
MIN_SAMPLES = 50
MIN_T_STAT = 2.0
MIN_WIN_RATE = 0.50
MIN_MEAN_RETURN = 0.0
GATE_WINDOWS = ("1m", "3m")   # 이 중 하나라도 통과하면 승격


@dataclass
class ValidationDecision:
    event_type: str
    validated: bool
    reasons: list[str] = field(default_factory=list)
    tested_windows: list[str] = field(default_factory=list)
    passing_window: Optional[str] = None


async def run_event_study_from_db(
    event_type: str,
    since: Optional[date] = None,
    windows: dict = WINDOW_DAYS,
    ticker_filter: Optional[set[str]] = None,
) -> AggregatedResult:
    """DB PowderKegEvent 에서 event_type 인 것들을 로드 → CAR 집계.

    Args:
        event_type: "A1" · "A3" · "B1" 등
        since: 이 날짜 이후 이벤트만 · None 이면 전체
        ticker_filter: 이 종목 집합에 속한 이벤트만 (v1.10 · 화약고 층화 백테스트)
    """
    async with get_session() as session:
        stmt = select(PowderKegEvent).where(PowderKegEvent.event_type == event_type)
        if since is not None:
            from datetime import datetime, timezone as tz
            stmt = stmt.where(PowderKegEvent.release_date >= datetime.combine(since, datetime.min.time(), tzinfo=tz.utc))
        events = list((await session.execute(stmt)).scalars().all())

    if ticker_filter is not None:
        events = [e for e in events if e.ticker in ticker_filter]

    returns: list[SingleEventReturn] = []
    for e in events:
        if e.release_date is None:
            continue
        d = e.release_date.date()
        r = await compute_event_return(e.ticker, d, windows=windows)
        returns.append(r)

    return aggregate_returns(event_type, returns, windows)


# ═══════════════════════════════════════════════════════════════
# P2-2 · PIT (Point-In-Time) 층화 백테스트 (v1.41)
# ═══════════════════════════════════════════════════════════════
#
# 목표 · 각 이벤트 release_date 시점에 화약고였던 종목만 표본에 포함
# (기존 powderkeg_passed 는 오늘 리스트 · look-ahead + 생존 편향).
#
# Phase 1 실용 접근 · 재무·지분·big_biz 6조건 as-of · 시장(1·9)/관리(10)는 관대 처리.

_PIT_UNMEASURED = ["1_pbr", "9_adv60", "10_no_bad_history"]


async def _as_of_financials(
    ticker: str,
    as_of_date: date,
    report_code: str = "11011",
    limit: int = 3,
) -> list[FinancialSnapshot]:
    """release_date <= as_of_date 인 재무 스냅샷을 최신순으로."""
    from datetime import datetime, time as _time, timezone as _tz
    as_of_dt = datetime.combine(as_of_date, _time.max, tzinfo=_tz.utc)
    async with get_session() as session:
        stmt = (
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.ticker == ticker,
                FinancialSnapshot.report_code == report_code,
                FinancialSnapshot.release_date <= as_of_dt,
            )
            .order_by(FinancialSnapshot.reference_date.desc(), FinancialSnapshot.release_date.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())


async def _as_of_shareholder(ticker: str, as_of_date: date) -> Optional[MajorShareholder]:
    """release_date <= as_of_date 인 최대주주 최신."""
    from datetime import datetime, time as _time, timezone as _tz
    as_of_dt = datetime.combine(as_of_date, _time.max, tzinfo=_tz.utc)
    async with get_session() as session:
        stmt = (
            select(MajorShareholder)
            .where(
                MajorShareholder.ticker == ticker,
                MajorShareholder.release_date <= as_of_dt,
            )
            .order_by(MajorShareholder.reference_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


def _period_from_fs(fs: FinancialSnapshot) -> FinancialPeriod:
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


async def pit_evaluate(
    ticker: str,
    as_of_date: date,
    thresholds: Optional[dict] = None,
) -> tuple[bool, dict[str, Any]]:
    """P2-2 · 이벤트 시점 화약고 여부 재평가 (Phase 1 · 6조건).

    평가 조건 · 3 owner · 4 not_big_biz · 5 audit · 6 cash_reality · 7 op_profit · 8 fscore
    관대 처리 (통과 가정) · 1 pbr · 9 adv60 · 10 no_bad_history · 2 net_cash (시가총액 부재)

    Returns:
        (passed_pit, meta)
        meta.reason 은 실패 시 요약 · meta.cond 는 조건별 판정 값
    """
    t = thresholds or {}
    fscore_min = t.get("piotroski_f_score_min", 6)
    owner_min = t.get("major_shareholder_pct_min", 0.40)
    base_rate = t.get("boK_base_rate", 0.035)
    interest_margin = t.get("interest_income_yield_margin", 0.5)

    meta: dict[str, Any] = {"cond": {}, "unmeasured": list(_PIT_UNMEASURED), "reason": None}

    fin_all = await _as_of_financials(ticker, as_of_date)
    if not fin_all:
        meta["reason"] = "no_financial_data"
        return False, meta
    holder = await _as_of_shareholder(ticker, as_of_date)

    fin = fin_all[0]
    # 3 owner
    if holder is None:
        meta["cond"]["3_owner"] = None
    else:
        owner = (holder.major_pct or 0) + (holder.related_pct or 0)
        meta["cond"]["3_owner"] = owner >= owner_min

    # 5 audit (2년)
    audits = [f.audit_opinion for f in fin_all[:2] if f.audit_opinion]

    def _adequate(op: str) -> bool:
        op = (op or "").strip()
        if not op:
            return False
        if any(bad in op for bad in ("한정", "부적정", "의견거절")):
            return False
        return "적정" in op

    if len(audits) < 2:
        meta["cond"]["5_audit"] = None
    else:
        meta["cond"]["5_audit"] = all(_adequate(op) for op in audits[:2])

    # 6 cash_reality
    cash_current = (fin.cash_and_equivalents or 0) + (fin.short_term_investments or 0)
    cash_prior = None
    if len(fin_all) >= 2:
        p = fin_all[1]
        cash_prior = (p.cash_and_equivalents or 0) + (p.short_term_investments or 0)
    cash_check = verify_cash_reality(
        interest_income=fin.interest_income,
        cash_current=cash_current if cash_current > 0 else None,
        cash_prior=cash_prior if cash_prior and cash_prior > 0 else None,
        base_rate=base_rate, margin=interest_margin,
    )
    meta["cond"]["6_cash_reality"] = cash_check.passed

    # 7 op_profit (3년 중 2년 흑자)
    ops = [f.operating_income for f in fin_all[:3] if f.operating_income is not None]
    positive = sum(1 for op in ops if op > 0)
    if len(ops) < 3:
        meta["cond"]["7_op_profit"] = None
    else:
        meta["cond"]["7_op_profit"] = positive >= 2

    # 8 fscore (2년 필요)
    if len(fin_all) >= 2:
        fscore = calculate_f_score(
            current=_period_from_fs(fin_all[0]),
            prior=_period_from_fs(fin_all[1]),
        )
        meta["cond"]["8_fscore"] = fscore.total_score >= fscore_min
    else:
        meta["cond"]["8_fscore"] = None

    # 4 not_big_biz (release_date.year 근사)
    is_big = await is_big_biz_group(ticker, as_of_date.year)
    meta["cond"]["4_not_big_biz"] = not is_big

    # 통합 판정 · 명시적 True 만 통과 (None/False 는 실패)
    passed = all(v is True for v in meta["cond"].values())
    if not passed:
        failed = [k for k, v in meta["cond"].items() if v is not True]
        meta["reason"] = f"failed_conds:{','.join(failed)}"
    return passed, meta


async def run_stratified_backtest(
    event_type: str,
    stratum: str = "powderkeg_passed",
    since: Optional[date] = None,
    thresholds: Optional[dict] = None,
) -> dict[str, Any]:
    """화약고 층화 백테스트 · 지시서 §7-4 스펙 (§10-5 층화).

    v1.10 · 리뷰어 지적:
      "전체 시장의 담보제공(-11.67%)은 '일반 종목에서 담보제공=부실 신호' 증명일 뿐.
       화약고 가설은 '10조건 통과 종목의 담보제공=현금부자 오너의 현금 수요' 교집합 명제."

    stratum:
      · powderkeg_passed · 화약고 리스트 status=passed 종목만 (교집합 검증)
      · all              · 전체 시장 (기존 · 대조군)
    """
    import json as _json
    from datetime import datetime, timezone as _tz
    ticker_filter: Optional[set[str]] = None
    stratum_meta: dict[str, Any] = {"name": stratum}
    pit_meta: Optional[dict[str, Any]] = None
    if stratum == "powderkeg_passed":
        # 최신 run_id 의 passed 종목만 필터
        from backend.services.models import PowderKegList
        async with get_session() as session:
            latest_run = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            if latest_run is None:
                return {"error": "no_powderkeg_run"}
            tickers = (await session.execute(
                select(PowderKegList.ticker).where(
                    PowderKegList.run_id == latest_run,
                    PowderKegList.status == "passed",
                )
            )).scalars().all()
        ticker_filter = set(tickers)
        stratum_meta["run_id"] = latest_run
        stratum_meta["ticker_count"] = len(ticker_filter)

    if stratum == "powderkeg_pit":
        # P2-2 · 각 이벤트 release_date 시점에 화약고였던 종목만 표본
        async with get_session() as session:
            stmt = select(PowderKegEvent).where(PowderKegEvent.event_type == event_type)
            if since is not None:
                stmt = stmt.where(PowderKegEvent.release_date >= datetime.combine(since, datetime.min.time(), tzinfo=_tz.utc))
            all_events = list((await session.execute(stmt)).scalars().all())

        pit_stats = {
            "total_events": len(all_events),
            "excluded_no_release_date": 0,
            "excluded_no_financial": 0,
            "excluded_failed_pit": 0,
            "pit_passed": 0,
            "unmeasured_conditions": list(_PIT_UNMEASURED),
        }
        pit_passed_events: list[PowderKegEvent] = []
        for e in all_events:
            if e.release_date is None:
                pit_stats["excluded_no_release_date"] += 1
                continue
            passed, meta = await pit_evaluate(e.ticker, e.release_date.date(), thresholds=thresholds)
            if passed:
                pit_stats["pit_passed"] += 1
                pit_passed_events.append(e)
            else:
                if meta.get("reason") == "no_financial_data":
                    pit_stats["excluded_no_financial"] += 1
                else:
                    pit_stats["excluded_failed_pit"] += 1

        # 표본에서 직접 CAR 계산 (run_event_study_from_db 재호출 없이)
        returns: list[SingleEventReturn] = []
        for e in pit_passed_events:
            d = e.release_date.date()
            r = await compute_event_return(e.ticker, d, windows=WINDOW_DAYS)
            returns.append(r)
        agg = aggregate_returns(event_type, returns, WINDOW_DAYS)
        stratum_meta["pit"] = pit_stats
        pit_meta = pit_stats
    else:
        agg = await run_event_study_from_db(event_type, since=since, ticker_filter=ticker_filter)

    decision = evaluate_validation(agg)

    # 캐시 저장 (event_type_stratum 키로 별도 저장)
    cache_key = f"{event_type}__{stratum}"
    async with get_session() as session:
        prev = (await session.execute(
            select(PowderKegBacktestReport).where(PowderKegBacktestReport.event_type == cache_key)
        )).scalar_one_or_none()
        agg_dict = _serialize_agg(agg)
        decision_dict = asdict(decision)
        if prev is None:
            session.add(PowderKegBacktestReport(
                event_type=cache_key,
                aggregate_json=_json.dumps(agg_dict, ensure_ascii=False),
                decision_json=_json.dumps(decision_dict, ensure_ascii=False),
                total_events=agg.total_events,
                valid_events=agg.valid_events,
                validated=decision.validated,
            ))
        else:
            prev.aggregate_json = _json.dumps(agg_dict, ensure_ascii=False)
            prev.decision_json = _json.dumps(decision_dict, ensure_ascii=False)
            prev.total_events = agg.total_events
            prev.valid_events = agg.valid_events
            prev.validated = decision.validated

    return {
        "event_type": event_type,
        "stratum": stratum_meta,
        "aggregate": agg_dict,
        "decision": decision_dict,
        "pit_meta": pit_meta,
    }


def evaluate_validation(result: AggregatedResult) -> ValidationDecision:
    """AggregatedResult → validated 승격 여부 판정 (지시서 §7-4)."""
    decision = ValidationDecision(event_type=result.event_type, validated=False)
    decision.tested_windows = list(result.per_window.keys())

    if result.valid_events < MIN_SAMPLES:
        decision.reasons.append(f"insufficient_samples({result.valid_events}<{MIN_SAMPLES})")
        return decision

    for label in GATE_WINDOWS:
        w = result.per_window.get(label)
        if w is None:
            continue
        problems: list[str] = []
        if w.t_stat <= MIN_T_STAT:
            problems.append(f"{label}.t_stat={w.t_stat}<={MIN_T_STAT}")
        if w.win_rate < MIN_WIN_RATE:
            problems.append(f"{label}.win_rate={w.win_rate}<{MIN_WIN_RATE}")
        if w.mean_return < MIN_MEAN_RETURN:
            problems.append(f"{label}.mean_return={w.mean_return}<{MIN_MEAN_RETURN}")
        if not problems:
            decision.validated = True
            decision.passing_window = label
            decision.reasons.append(f"passed_on_{label}")
            return decision
        decision.reasons.extend(problems)

    if not decision.reasons:
        decision.reasons.append("no_gate_window_available")
    return decision


async def apply_validation(event_type: str, decision: ValidationDecision) -> int:
    """decision.validated=True 이면 event_type 전체 · PowderKegEvent.validated=True."""
    if not decision.validated:
        return 0
    async with get_session() as session:
        stmt = update(PowderKegEvent).where(
            PowderKegEvent.event_type == event_type
        ).values(validated=True)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)


async def run_backtest_for_event_type(
    event_type: str,
    since: Optional[date] = None,
) -> dict[str, Any]:
    """이벤트 타입 백테스트 · aggregate + validation + apply + 캐시 저장.

    §9-3 cache (2026-07-16): 결과를 PowderKegBacktestReport 에 upsert.
    GET /report/{event_type} 는 캐시만 읽어 즉시 응답 (5년 표본 FDR fetch 60s 초과 대응).

    Returns:
        {
          "event_type": ..., "aggregate": {..., "per_window": {...}},
          "decision": {"validated": bool, "reasons": [...]},
          "updated_rows": N (validated=True 로 갱신된 event 수)
        }
    """
    import json as _json
    agg = await run_event_study_from_db(event_type, since=since)
    decision = evaluate_validation(agg)
    updated = await apply_validation(event_type, decision)

    agg_dict = _serialize_agg(agg)
    decision_dict = asdict(decision)

    async with get_session() as session:
        prev = (await session.execute(
            select(PowderKegBacktestReport).where(PowderKegBacktestReport.event_type == event_type)
        )).scalar_one_or_none()
        if prev is None:
            session.add(PowderKegBacktestReport(
                event_type=event_type,
                aggregate_json=_json.dumps(agg_dict, ensure_ascii=False),
                decision_json=_json.dumps(decision_dict, ensure_ascii=False),
                total_events=agg.total_events,
                valid_events=agg.valid_events,
                validated=decision.validated,
            ))
        else:
            prev.aggregate_json = _json.dumps(agg_dict, ensure_ascii=False)
            prev.decision_json = _json.dumps(decision_dict, ensure_ascii=False)
            prev.total_events = agg.total_events
            prev.valid_events = agg.valid_events
            prev.validated = decision.validated

    return {
        "event_type": event_type,
        "aggregate": agg_dict,
        "decision": decision_dict,
        "updated_rows": updated,
    }


async def read_cached_report(event_type: str) -> Optional[dict[str, Any]]:
    """캐시된 백테스트 리포트 반환 · 없으면 None (GET /report/{event_type} 용)."""
    import json as _json
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegBacktestReport).where(PowderKegBacktestReport.event_type == event_type)
        )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "event_type": row.event_type,
        "aggregate": _json.loads(row.aggregate_json),
        "decision": _json.loads(row.decision_json),
        "updated_rows": 0,
        "cached_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_agg(agg: AggregatedResult) -> dict:
    return {
        "event_type": agg.event_type,
        "total_events": agg.total_events,
        "valid_events": agg.valid_events,
        "per_window": {k: asdict(v) for k, v in agg.per_window.items()},
        "error_counts": agg.error_counts,
    }
