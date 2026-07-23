"""Powder Keg API 라우트 · Phase 7-6.

원칙 (지시서 §7-6-2):
    - 모든 화면 하단 고지: "본 화면은 공시·재무 데이터 기반 관찰 후보이며
      투자 권유가 아닙니다. 오너 관련 이벤트 표기는 공시·언론 보도 사실의 인용입니다."
    - 오너 개인 사건 표기는 공시/기사 원문 링크만 · 판단 문구 X (§7-6-3 명예훼손 방지).

라우트 분류:
    조회 (인증 없음)
        GET /list · GET /events · GET /report/{event_type}
        GET /tickets · GET /disclaimer
    편집·실행 (X-API-Token · require_sniper_token 재사용)
        POST /screener/run · POST /backtest/{event_type}
        POST /triggers/process
        POST /ticket · PATCH /ticket/{id}/approve · PATCH /ticket/{id}/reject
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

from backend.api.auth import require_sniper_token
from backend.powderkeg.backtest import (
    run_backtest_for_event_type,
    run_stratified_backtest,
)
from backend.powderkeg.collectors.corp_codes import (
    refresh_corp_codes,
    resolve_corp_code,
    resolve_many,
)
from backend.powderkeg.collectors.dart_financials import collect_batch as dart_collect_batch
from backend.powderkeg.collectors.dart_shareholders import collect_batch as sh_collect_batch
from backend.powderkeg.collectors.events import backfill_powderkeg_events, poll_powderkeg_events
from backend.powderkeg.collectors.ftc_big_biz import list_all as list_big_biz, refresh_from_seed
from backend.powderkeg.collectors.krx_market import collect_market_snapshot
from backend.powderkeg.collectors.order_industry_seed import (
    order_industry_info, financial_industry_info,
)
from backend.powderkeg.orders import (
    TicketCreateRequest,
    TicketValidationError,
    approve_ticket,
    check_holding_expiry,
    create_ticket,
    reject_ticket,
)
from backend.powderkeg.screener import run_screener
from backend.powderkeg.triggers import process_pending_events
from backend.services.db import get_session
from backend.services.models import (
    FinancialSnapshot,
    KrxMarketSnapshot,
    MajorShareholder,
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
    PowderKegRun,
    PowderKegRunDiff,
)

logger = logging.getLogger(__name__)
router = APIRouter()


DISCLAIMER = (
    "본 화면은 공시·재무 데이터 기반 관찰 후보이며 투자 권유가 아닙니다. "
    "오너 관련 이벤트 표기는 공시·언론 보도 사실의 인용입니다."
)


# ═══════════════════════════════════════════════════════════════
# 조회 (인증 없음)
# ═══════════════════════════════════════════════════════════════
@router.get("/disclaimer")
async def get_disclaimer() -> dict[str, str]:
    return {"disclaimer": DISCLAIMER}


@router.get("/list/funnel")
async def get_list_funnel(
    run_id: Optional[str] = Query(None, description="특정 run · None = 최신"),
) -> dict[str, Any]:
    """퍼널 워터폴 · v1.18 · 리뷰어 진단 대응.

    "1개는 시장의 답이 아니라 파이프라인의 답" · 각 단계 통과 수 표시.

    반환:
      · universe_size · 이 run 에서 스크린된 종목 수
      · data_incomplete · 재무·시장·최대주주 결측 · 실 탈락 X
      · per_condition · 조건별 통과 수 (파이프라인 병목 파악)
      · final_passed · 10/10 최종 통과
    """
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            return {"disclaimer": DISCLAIMER, "run_id": None, "universe_size": 0}
        rows = (await session.execute(
            select(PowderKegList).where(PowderKegList.run_id == run_id)
        )).scalars().all()

    # 조건 label · 한국어
    CONDITION_LABELS = {
        "1_pbr": "① PBR < 0.5 (저평가)",
        "2_net_cash_ratio": "② 순현금/시총 > 40% (현금 부자)",
        "3_owner_pct": "③ 최대주주 지분 ≥ 40%",
        "4_not_big_biz": "④ 공정위 대기업집단 아님",
        "5_audit_opinion": "⑤ 감사의견 적정 (2년)",
        "6_cash_reality": "⑥ 이자수익 정합 (분식 X)",
        "7_operating_profit": "⑦ 영업이익 3년 중 2년 흑자",
        "8_fscore": "⑧ F-Score ≥ 6",
        "9_adv60": "⑨ 60일 일평균 거래대금 ≥ 1억",
        "10_no_bad_history": "⑩ 관리종목 이력 없음 (감사 3년 근사)",
    }

    universe_size = len(rows)
    data_incomplete = 0
    # v1.35 · 4차 리뷰 P4-4 · 3상태 분리 (통과/실패/결측)
    per_condition: dict[str, dict[str, int]] = {
        k: {"passed": 0, "failed": 0, "missing": 0} for k in CONDITION_LABELS
    }

    for r in rows:
        # 결측 · reject_reasons 에 no_financial_data / no_market_data / no_shareholder_data
        reasons = (r.reject_reasons or "")
        if any(k in reasons for k in ("no_financial_data", "no_market_data")):
            data_incomplete += 1
            continue
        # conditions_json 파싱
        try:
            conds = json.loads(r.conditions_json) if r.conditions_json else {}
        except Exception:  # noqa: BLE001
            continue
        for k in per_condition:
            v = conds.get(k)
            if v is True:
                per_condition[k]["passed"] += 1
            elif v is False:
                per_condition[k]["failed"] += 1
            elif v is None:
                per_condition[k]["missing"] += 1

    final_passed = sum(1 for r in rows if r.status == "passed")
    cash_suspect = sum(1 for r in rows if r.status == "cash_suspect")
    rejected = sum(1 for r in rows if r.status == "rejected")

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "universe_size": universe_size,
        "data_incomplete": data_incomplete,
        "evaluable": universe_size - data_incomplete,
        "per_condition": [
            {
                "id": k, "label": CONDITION_LABELS[k],
                "passed": per_condition[k]["passed"],
                "failed": per_condition[k]["failed"],
                "missing": per_condition[k]["missing"],
            }
            for k in CONDITION_LABELS
        ],
        "final_passed": final_passed,
        "cash_suspect": cash_suspect,
        "rejected": rejected,
    }


@router.get("/list")
async def get_list(
    run_id: Optional[str] = Query(None, description="특정 run · None = 최신"),
    status: Optional[str] = Query(None, description="passed / rejected / cash_suspect"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """탭 1 · 화약고 리스트."""
    async with get_session() as session:
        if run_id is None:
            latest = (await session.execute(
                select(PowderKegList.run_id).order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            run_id = latest
        if run_id is None:
            return {"disclaimer": DISCLAIMER, "run_id": None, "items": []}
        stmt = select(PowderKegList).where(PowderKegList.run_id == run_id)
        if status:
            stmt = stmt.where(PowderKegList.status == status)
        stmt = stmt.order_by(PowderKegList.net_cash_ratio.desc().nulls_last()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    def _extract_robustness(cond_json_str: Optional[str]) -> dict:
        """v1.14 · conditions_json 에서 _robustness meta 추출."""
        if not cond_json_str:
            return {}
        try:
            data = json.loads(cond_json_str)
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(data, dict) and "_robustness" in data:
            r = data["_robustness"]
            return {
                "robustness_score": r.get("score"),
                "robustness_grade": r.get("grade"),
                "condition_margins": r.get("margins", {}),
            }
        return {}

    def _compute_tier(
        cond: Optional[dict], status: str
    ) -> tuple[str, int, list[str], list[str]]:
        """v1.29 · 3차 리뷰 P1 · 3상태 분리 (True/False/None).

        · tier_1_passed      · 10/10 True                (매수 후보)
        · tier_2_near        · 9/10 True · missing=0     (실 실패 1건 · 경계선 관찰)
        · tier_2_needs_data  · missing≥1 · passed+missing ≥ total-1
                                                          (데이터 채우면 통과 가능)
        · tier_3_watch       · passed ≥ total-3 (7/10 이상, 관찰만)
        · cash_suspect       · status 가 cash_suspect
        · rejected           · 그 외

        Returns: (tier, conditions_passed, failed_condition_ids, missing_condition_ids)
        """
        if not isinstance(cond, dict):
            return ("rejected", 0, [], [])
        items = [(k, v) for k, v in cond.items() if k != "_robustness"]
        passed = sum(1 for _, v in items if v is True)
        failed = [k for k, v in items if v is False]
        missing = [k for k, v in items if v is None]
        total = len(items)
        # v1.34 · 4차 리뷰 P4-3 hotfix · conditions 비어있으면 rejected
        #   금융업 조기 return 시 conditions 미채움 → total==0 을 passed==total 로
        #   오판정해 tier_1_passed 표시되던 버그 차단.
        if total == 0:
            return ("rejected", 0, [], [])

        if status == "cash_suspect":
            return ("cash_suspect", passed, failed, missing)
        if passed == total:
            return ("tier_1_passed", passed, [], [])
        # 실 실패 1건 · 데이터 부족 없음
        if passed == total - 1 and not missing:
            return ("tier_2_near", passed, failed, [])
        # 데이터 부족은 있으나 (passed + missing) 로 9/10 이상 도달 가능
        if missing and (passed + len(missing)) >= total - 1:
            return ("tier_2_needs_data", passed, failed, missing)
        # 관찰 등급 · 실 통과 or 부분 부족 포함 7/10 이상
        if passed >= total - 3:
            return ("tier_3_watch", passed, failed, missing)
        return ("rejected", passed, failed, missing)

    def _fmt_pct(v, digits=1):
        try: return f"{v*100:.{digits}f}%"
        except (TypeError, ValueError): return "-"
    def _fmt_num(v, digits=3):
        try: return f"{v:.{digits}f}"
        except (TypeError, ValueError): return "-"

    def _auto_note(tier: str, row, rob_meta: dict, sector: Optional[str]) -> Optional[str]:
        """v1.36 · P5-1 · 자동 승격 근거 노트 (tier_1/tier_2_near 만).

        서희 파싱 오류 실증 후 · 승격 근거 provenance 확보 목적.
        user_note 와 별도 필드로 반환 · 사용자 수동 노트 침해 X.
        """
        if tier not in ("tier_1_passed", "tier_2_near"):
            return None
        parts = [f"[자동] Tier 1 승격" if tier == "tier_1_passed" else "[자동] Tier 2 경계 (9/10)"]
        if row.net_cash_ratio is not None:
            parts.append(f"nc={_fmt_pct(row.net_cash_ratio)}")
        if row.pbr is not None:
            parts.append(f"pbr={_fmt_num(row.pbr)}")
        if row.owner_pct is not None:
            parts.append(f"owner={_fmt_pct(row.owner_pct)}")
        if row.piotroski_f_score is not None:
            parts.append(f"F-Score={row.piotroski_f_score}/9")
        grade = rob_meta.get("robustness_grade")
        if grade:
            parts.append(f"강건={grade}")
        if sector:
            parts.append(f"업종={sector}")
        # 승격 시각 (created_at 기준 · run_id 참조)
        if row.created_at:
            parts.append(f"승격={row.created_at.strftime('%Y-%m-%d %H:%M')}")
        return " · ".join(parts)

    items = []
    for r in rows:
        cond = json.loads(r.conditions_json) if r.conditions_json else None
        # UI 는 boolean 조건만 필요 · _robustness 필드 제거 후 반환
        if isinstance(cond, dict) and "_robustness" in cond:
            cond = {k: v for k, v in cond.items() if k != "_robustness"}
        rob = _extract_robustness(r.conditions_json)
        tier, cond_passed, failed_ids, missing_ids = _compute_tier(cond, r.status)
        # v1.34 · 4차 리뷰 P4-hotfix · sector 필드 조회 시점 계산·노출
        #   PowderKegList DB 컬럼 없이 order/financial 시드 판별로 실시간 태깅.
        oi = order_industry_info(r.ticker)
        fi = financial_industry_info(r.ticker)
        if oi is not None:
            sector = oi[1]                          # "건설"/"조선"/"플랜트"
        elif fi is not None:
            sector = f"금융({fi[1]})"               # "금융(은행/증권/보험)"
        else:
            sector = None                           # 자동 판별(cl>3%) 은 reject_reasons 문자열 참조
        auto_note = _auto_note(tier, r, rob, sector)
        items.append({
            "id": r.id, "ticker": r.ticker, "name": r.name,
            "status": r.status, "net_cash_ratio": r.net_cash_ratio,
            "piotroski_f_score": r.piotroski_f_score,
            "owner_pct": r.owner_pct, "treasury_pct": r.treasury_pct,
            "pbr": r.pbr, "dividend_payout": r.dividend_payout,
            "conditions": cond,
            "reject_reasons": r.reject_reasons,
            "locked": getattr(r, "locked", False) or False,
            "added_by": getattr(r, "added_by", "auto") or "auto",
            "user_note": getattr(r, "user_note", None),
            "auto_note": auto_note,   # v1.36 · P5-1 · 자동 승격 근거
            "created_at": r.created_at.isoformat() if r.created_at else None,
            # v1.20 티어제 · v1.29 3차 리뷰 P1 · 3상태 분리 (missing 신규)
            "tier": tier,
            "conditions_passed": cond_passed,
            "failed_conditions": failed_ids,
            "missing_conditions": missing_ids,
            "order_industry_sector": sector,        # v1.34 · P4-hotfix
            **rob,
        })

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "count": len(rows),
        "items": items,
    }


@router.get("/events")
async def get_events(
    ticker: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """탭 2 · 불꽃 피드 (Type A/B 타임라인)."""
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    async with get_session() as session:
        stmt = select(PowderKegEvent).where(PowderKegEvent.detected_at >= since)
        if ticker:
            stmt = stmt.where(PowderKegEvent.ticker == ticker)
        if event_type:
            stmt = stmt.where(PowderKegEvent.event_type == event_type)
        stmt = stmt.order_by(PowderKegEvent.detected_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "disclaimer": DISCLAIMER,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "ticker": r.ticker, "event_type": r.event_type,
                "kind": "A" if r.event_type.startswith("A") else "B",
                "source": r.source, "source_id": r.source_id,
                "title": r.title,           # 원문 그대로 · 판단 문구 X
                "url": r.url,               # 원문 링크만 (§7-6-3)
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "release_date": r.release_date.isoformat() if r.release_date else None,
                "confidence": r.confidence,
                "needs_human_review": r.needs_human_review,
                "action_taken": r.action_taken,
                "validated": r.validated,
            }
            for r in rows
        ],
    }


@router.get("/ticker/{ticker}/detail")
async def get_ticker_detail(ticker: str) -> dict[str, Any]:
    """v1.36 · P5-2 · 종목 상세 (팝업용).

    포함:
    - 리스트 최신 항목 (tier·조건·auto_note·user_note)
    - 재무 3년 (2022·2023·2024 · 주요 지표)
    - 최대주주 최신
    - KRX 최신 스냅샷
    - 이벤트 이력 (최근 20건)
    - 외부 링크 (KRX·네이버 금융·DART)

    ⚠️ 예측 없음 · 사용자 판단 근거 제공만 (지시서 · hypothesis 상태 유지 원칙).
    """
    async with get_session() as session:
        # 리스트 최신 항목
        list_row = (await session.execute(
            select(PowderKegList)
            .where(PowderKegList.ticker == ticker)
            .order_by(PowderKegList.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        # 재무 3년
        fin_rows = (await session.execute(
            select(FinancialSnapshot)
            .where(FinancialSnapshot.ticker == ticker, FinancialSnapshot.report_code == "11011")
            .order_by(FinancialSnapshot.reference_date.desc())
            .limit(3)
        )).scalars().all()

        # 최대주주
        holder = (await session.execute(
            select(MajorShareholder)
            .where(MajorShareholder.ticker == ticker)
            .order_by(MajorShareholder.reference_date.desc())
            .limit(1)
        )).scalar_one_or_none()

        # KRX 최신
        krx = (await session.execute(
            select(KrxMarketSnapshot)
            .where(KrxMarketSnapshot.ticker == ticker)
            .order_by(KrxMarketSnapshot.snapshot_date.desc())
            .limit(1)
        )).scalar_one_or_none()

        # 이벤트 이력
        events = (await session.execute(
            select(PowderKegEvent)
            .where(PowderKegEvent.ticker == ticker)
            .order_by(PowderKegEvent.detected_at.desc())
            .limit(20)
        )).scalars().all()

    if list_row is None and krx is None:
        raise HTTPException(status_code=404, detail=f"ticker {ticker} not found")

    name = (list_row.name if list_row else None) or (krx.name if krx else ticker)

    # 외부 링크 (KRX·네이버 금융·DART)
    external_links = {
        "krx_chart": f"http://data.krx.co.kr/contents/COM/GetIssueInfo.do?issuecode={ticker}",
        "naver_finance": f"https://finance.naver.com/item/main.naver?code={ticker}",
        "daum_finance": f"https://finance.daum.net/quotes/A{ticker}",
        "dart_corp": f"https://dart.fss.or.kr/dsae001/mainY.do?selectKey={ticker}",
    }

    return {
        "disclaimer": DISCLAIMER,
        "ticker": ticker,
        "name": name,
        "list_item": {
            "id": list_row.id,
            "status": list_row.status,
            "conditions": json.loads(list_row.conditions_json) if list_row.conditions_json else None,
            "reject_reasons": list_row.reject_reasons,
            "locked": bool(getattr(list_row, "locked", False)),
            "user_note": getattr(list_row, "user_note", None),
            "run_id": list_row.run_id,
            "created_at": list_row.created_at.isoformat() if list_row.created_at else None,
        } if list_row else None,
        "financials_3y": [
            {
                "reference_date": f.reference_date,
                "release_date": f.release_date.isoformat() if f.release_date else None,
                "cash_and_equivalents": f.cash_and_equivalents,
                "short_term_investments": f.short_term_investments,
                "total_debt": f.total_debt,
                "contract_liabilities": getattr(f, "contract_liabilities", None),
                "total_equity": f.total_equity,
                "revenue": f.revenue,
                "operating_income": f.operating_income,
                "net_income": f.net_income,
                "interest_income": f.interest_income,
                "audit_opinion": f.audit_opinion,
            }
            for f in fin_rows
        ],
        "shareholder": {
            "reference_date": holder.reference_date,
            "major_pct": holder.major_pct,
            "related_pct": holder.related_pct,
            "treasury_pct": holder.treasury_pct,
        } if holder else None,
        "market": {
            "snapshot_date": krx.snapshot_date,
            "market": krx.market,
            "close_price": krx.close_price,
            "market_cap": krx.market_cap,
            "pbr": krx.pbr,
            "avg_daily_amount_60d": krx.avg_daily_amount_60d,
        } if krx else None,
        "events": [
            {
                "id": e.id, "event_type": e.event_type,
                "kind": "A" if e.event_type.startswith("A") else "B",
                "source": e.source, "title": e.title, "url": e.url,
                "detected_at": e.detected_at.isoformat() if e.detected_at else None,
                "release_date": e.release_date.isoformat() if e.release_date else None,
                "action_taken": e.action_taken,
            }
            for e in events
        ],
        "external_links": external_links,
    }


# ═══════════════════════════════════════════════════════════════
# P4-1 · Provenance + Run diff (2026-07-22 신설)
# ═══════════════════════════════════════════════════════════════

# 조건별 원천 컬렉터 매핑 (v1.38)
_CONDITION_PROVENANCE = {
    "1_pbr": ("krx_market", "KRX 시장 스냅샷 (PBR 미제공 시 book_value 로 계산)"),
    "2_net_cash_ratio": ("dart_financials", "DART 재무제표 (현금·단기금융상품·총차입금·계약부채)"),
    "3_owner_pct": ("dart_shareholders", "DART 최대주주 현황"),
    "4_not_big_biz": ("ftc_big_biz", "공정위 공시대상기업집단 seed"),
    "5_audit_opinion": ("dart_financials", "DART 감사의견"),
    "6_cash_reality": ("dart_financials", "DART 이자수익 · BOK 기준금리 교차검증"),
    "7_operating_profit": ("dart_financials", "DART 3년 영업이익 (2 흑자 필요)"),
    "8_fscore": ("dart_financials", "Piotroski F-Score 계산 (2년 재무)"),
    "9_adv60": ("krx_market", "KRX 60일 일평균 거래대금"),
    "10_no_bad_history": ("dart_financials", "DART 3년 감사의견 근사 (관리종목 대안)"),
}


@router.get("/ticker/{ticker}/provenance")
async def get_ticker_provenance(ticker: str) -> dict[str, Any]:
    """P4-1 · 조건별 최근 값 + 출처(원천 컬렉터 · 수집 시각).

    UI 활용: 상세 팝업 "변동 이력" 탭 상단 · 각 조건의 근거 노출.
    """
    async with get_session() as session:
        list_row = (await session.execute(
            select(PowderKegList)
            .where(PowderKegList.ticker == ticker)
            .order_by(PowderKegList.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        fin_latest = (await session.execute(
            select(FinancialSnapshot)
            .where(FinancialSnapshot.ticker == ticker, FinancialSnapshot.report_code == "11011")
            .order_by(FinancialSnapshot.reference_date.desc(), FinancialSnapshot.release_date.desc())
            .limit(1)
        )).scalar_one_or_none()

        holder = (await session.execute(
            select(MajorShareholder)
            .where(MajorShareholder.ticker == ticker)
            .order_by(MajorShareholder.reference_date.desc())
            .limit(1)
        )).scalar_one_or_none()

        krx = (await session.execute(
            select(KrxMarketSnapshot)
            .where(KrxMarketSnapshot.ticker == ticker)
            .order_by(KrxMarketSnapshot.snapshot_date.desc())
            .limit(1)
        )).scalar_one_or_none()

    if list_row is None:
        raise HTTPException(status_code=404, detail=f"ticker {ticker} not found")

    conds = {}
    try:
        conds = json.loads(list_row.conditions_json) if list_row.conditions_json else {}
    except Exception:  # noqa: BLE001
        conds = {}

    # 컬렉터별 최종 수집 시각
    collector_ts = {
        "dart_financials": fin_latest.release_date.isoformat() if (fin_latest and fin_latest.release_date) else None,
        "dart_shareholders": holder.reference_date if holder else None,
        "krx_market": krx.snapshot_date if krx else None,
        "ftc_big_biz": None,  # year 단위 seed · 시각 정보 없음
    }

    provenance = []
    for key, (collector, desc) in _CONDITION_PROVENANCE.items():
        provenance.append({
            "condition_key": key,
            "value": conds.get(key),
            "collector": collector,
            "description": desc,
            "collected_at": collector_ts.get(collector),
        })

    return {
        "disclaimer": DISCLAIMER,
        "ticker": ticker,
        "run_id": list_row.run_id,
        "provenance": provenance,
        "collector_freshness": collector_ts,
    }


@router.get("/run-diff/latest")
async def get_run_diff_latest(
    ticker: str = Query(..., description="종목 코드 (필수)"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """P4-1 · 종목별 최근 diff (변화 이력).

    UI 활용: 상세 팝업 "변동 이력" 탭 목록.
    """
    async with get_session() as session:
        rows = (await session.execute(
            select(PowderKegRunDiff)
            .where(PowderKegRunDiff.ticker == ticker)
            .order_by(PowderKegRunDiff.changed_at.desc())
            .limit(limit)
        )).scalars().all()

    def _decode(v: Optional[str]) -> Any:
        if v is None:
            return None
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v

    return {
        "disclaimer": DISCLAIMER,
        "ticker": ticker,
        "items": [
            {
                "run_id": r.run_id,
                "condition_key": r.condition_key,
                "prev_value": _decode(r.prev_value),
                "curr_value": _decode(r.curr_value),
                "prev_status": r.prev_status,
                "curr_status": r.curr_status,
                "changed_at": r.changed_at.isoformat() if r.changed_at else None,
                "reason_hint": r.reason_hint,
            }
            for r in rows
        ],
    }


@router.get("/run-diff/summary")
async def get_run_diff_summary(
    run_id: Optional[str] = Query(None, description="특정 run · None = 최신"),
) -> dict[str, Any]:
    """P4-1 · 최근 run 에서 변화 있는 종목 요약.

    UI 활용: 리스트 상단 요약 카드 + 리스트 뱃지 소스.
    """
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegRun.run_id)
                .order_by(PowderKegRun.started_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            return {"disclaimer": DISCLAIMER, "run_id": None, "items": []}

        rows = (await session.execute(
            select(PowderKegRunDiff)
            .where(PowderKegRunDiff.run_id == run_id)
            .order_by(PowderKegRunDiff.ticker)
        )).scalars().all()

        run_meta = (await session.execute(
            select(PowderKegRun).where(PowderKegRun.run_id == run_id)
        )).scalar_one_or_none()

    # ticker → diff 그룹핑 · tier 이동 여부 강조
    by_ticker: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by_ticker.setdefault(r.ticker, {
            "ticker": r.ticker,
            "diff_count": 0,
            "tier_moved": False,
            "prev_tier": None,
            "curr_tier": None,
            "condition_changes": [],
        })
        b["diff_count"] += 1
        if r.condition_key == "tier":
            b["tier_moved"] = True
            b["prev_tier"] = r.prev_status
            b["curr_tier"] = r.curr_status
        else:
            b["condition_changes"].append({
                "condition_key": r.condition_key,
                "prev_status": r.prev_status,
                "curr_status": r.curr_status,
            })

    items = sorted(by_ticker.values(), key=lambda x: (not x["tier_moved"], -x["diff_count"]))

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "run_started_at": run_meta.started_at.isoformat() if (run_meta and run_meta.started_at) else None,
        "run_ended_at": run_meta.ended_at.isoformat() if (run_meta and run_meta.ended_at) else None,
        "run_trigger": run_meta.trigger if run_meta else None,
        "run_git_sha": run_meta.git_sha if run_meta else None,
        "tier_moved_count": sum(1 for i in items if i["tier_moved"]),
        "total_changed_tickers": len(items),
        "items": items,
    }


@router.get("/report/{event_type}")
async def get_report(event_type: str) -> dict[str, Any]:
    """탭 3 · 백테스트 리포트 (캐시 읽기 · §9-3 · 5년 표본 60s 초과 대응).

    캐시 없으면 empty 응답 · POST /backtest/{event_type} 트리거 필요.
    """
    from backend.powderkeg.backtest import read_cached_report
    cached = await read_cached_report(event_type)
    if cached is None:
        return {
            "event_type": event_type,
            "aggregate": {"event_type": event_type, "total_events": 0, "valid_events": 0, "per_window": {}, "error_counts": {}},
            "decision": {"event_type": event_type, "validated": False, "reasons": ["no_cache_run_backtest"], "tested_windows": [], "passing_window": None},
            "updated_rows": 0,
            "cached_at": None,
            "disclaimer": DISCLAIMER,
        }
    cached["disclaimer"] = DISCLAIMER
    return cached


@router.get("/tickets")
async def get_tickets(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket)
        if status:
            stmt = stmt.where(PowderKegOrderTicket.status == status)
        stmt = stmt.order_by(PowderKegOrderTicket.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    return {
        "disclaimer": DISCLAIMER,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "event_id": r.event_id, "ticker": r.ticker,
                "proposed_qty": r.proposed_qty, "proposed_price": r.proposed_price,
                "invalidation_price": r.invalidation_price,
                "invalidation_logic": r.invalidation_logic,
                "status": r.status, "approver": r.approver,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "holding_days_max": r.holding_days_max,
                "executed_order_uuid": r.executed_order_uuid,
            }
            for r in rows
        ],
    }


@router.get("/holding-expiry")
async def get_expiry() -> dict[str, Any]:
    """12개월 초과 재평가 대상."""
    expired = await check_holding_expiry()
    return {"disclaimer": DISCLAIMER, "count": len(expired), "items": expired}


# ═══════════════════════════════════════════════════════════════
# 편집·실행 (X-API-Token 필수)
# ═══════════════════════════════════════════════════════════════
# ─── corp_code 매핑 (Phase 7-1g) ────────────────
@router.post("/collectors/corp-codes-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_corp_codes_refresh() -> dict[str, Any]:
    """DART fetch_corp_codes → DartCorpCodeMap 갱신 (월 1회 권장)."""
    return await refresh_corp_codes()


@router.get("/corp-code/{ticker}")
async def get_corp_code(ticker: str) -> dict[str, Optional[str]]:
    """KRX 6자리 → corp_code 조회 · UI 확인용."""
    cc = await resolve_corp_code(ticker)
    return {"ticker": ticker, "corp_code": cc}


@router.patch("/list/{item_id}/lock", dependencies=[Depends(require_sniper_token)])
async def toggle_list_lock(item_id: int, locked: bool = Body(..., embed=True)) -> dict[str, Any]:
    """리스트 항목 lock 토글 · locked=True 는 스크리너 재실행 후에도 유지 (Watchlist 패턴)."""
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegList).where(PowderKegList.id == item_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found")
        row.locked = bool(locked)
        if locked:
            row.added_by = "user"
    return {"id": item_id, "locked": bool(locked)}


@router.patch("/list/{item_id}/note", dependencies=[Depends(require_sniper_token)])
async def update_list_note(item_id: int, note: str = Body("", embed=True)) -> dict[str, Any]:
    """사용자 코멘트 저장 (분석 노트 · 사유 등)."""
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegList).where(PowderKegList.id == item_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found")
        row.user_note = note.strip() or None
    return {"id": item_id, "user_note": note.strip() or None}


@router.post("/list/manual", dependencies=[Depends(require_sniper_token)])
async def add_manual_to_list(
    ticker: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True),
    note: Optional[str] = Body(None, embed=True),
) -> dict[str, Any]:
    """사용자 수동 추가 · locked=True · added_by='user' · 스크리너 후에도 유지."""
    ticker = ticker.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    from backend.powderkeg.collectors.corp_codes import resolve_corp_code
    from backend.services.models import KrxMarketSnapshot as KRX
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        # name 자동 해결 (KRX 스냅샷)
        stmt = (
            select(KRX.name)
            .where(KRX.ticker == ticker, KRX.name.is_not(None))
            .order_by(KRX.snapshot_date.desc()).limit(1)
        )
        name = (await session.execute(stmt)).scalar_one_or_none() or ticker
        # 이미 있으면 lock+note 만 갱신
        existing = (await session.execute(
            select(PowderKegList).where(
                PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
            )
        )).scalar_one_or_none()
        if existing:
            existing.locked = True
            existing.added_by = "user"
            if note:
                existing.user_note = note
            item_id = existing.id
        else:
            row = PowderKegList(
                run_id=run_id, ticker=ticker, name=name,
                status="passed", locked=True, added_by="user",
                user_note=note,
            )
            session.add(row)
            await session.flush()
            item_id = row.id
    logger.info("[powderkeg.manual_add] ticker=%s run=%s note=%s", ticker, run_id, note)
    return {"id": item_id, "ticker": ticker, "name": name, "run_id": run_id, "locked": True}


@router.post("/admin/list/remove", dependencies=[Depends(require_sniper_token)])
async def admin_remove_from_list(
    ticker: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True, description="None = 최신 run"),
    reason: Optional[str] = Body(None, embed=True),
) -> dict[str, Any]:
    """수동 · 화약고 리스트에서 특정 종목 완전 제거 (감사 로그 + lock 해제).

    v1.17 (2026-07-16 · 버그 fix):
      · 삭제 후 재평가 시 · 과거 run 에 남아있는 locked=True 흔적으로 재승격되는 문제 fix
      · 모든 run 에서 해당 ticker · locked=False 로 갱신 · union 재승격 차단

    용도: cash_suspect · 지주회사 특성 · 사용자 판단으로 리스트에서 배제.
    """
    from sqlalchemy import delete as _delete, update as _update
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            raise HTTPException(status_code=404, detail="no runs exist")
        # 감사 로그 · 삭제 전 스냅샷
        stmt = select(PowderKegList).where(
            PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"ticker {ticker} not in run {run_id}")
        snapshot = {
            "ticker": row.ticker, "name": row.name, "status": row.status,
            "pbr": row.pbr, "net_cash_ratio": row.net_cash_ratio,
            "owner_pct": row.owner_pct, "reason_removed": reason,
        }
        # (a) 최신 run 에서 삭제
        result = await session.execute(
            _delete(PowderKegList).where(
                PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
            )
        )
        # (b) v1.17 · 모든 run 에서 lock 해제 · 재승격 차단
        unlock_result = await session.execute(
            _update(PowderKegList).where(
                PowderKegList.ticker == ticker,
                PowderKegList.locked == True,   # noqa: E712
            ).values(locked=False)
        )
    logger.info("[powderkeg.admin] removed · ticker=%s run=%s reason=%s unlocked_runs=%d snapshot=%s",
                ticker, run_id, reason, int(unlock_result.rowcount or 0), snapshot)
    return {
        "deleted": int(result.rowcount or 0),
        "unlocked_runs": int(unlock_result.rowcount or 0),
        "run_id": run_id, "snapshot": snapshot,
    }


# ─── 수동 스키마 마이그레이션 · SQLite CREATE / ALTER ─
@router.post("/admin/migrate-schema", dependencies=[Depends(require_sniper_token)])
async def migrate_schema() -> dict[str, Any]:
    """스키마 마이그레이션:
    1. Base.metadata.create_all · 미존재 테이블 생성 (신규 모델 반영)
    2. ALTER TABLE ADD COLUMN · 기존 테이블 컬럼 추가 (SQLite 제약 우회)
    """
    from sqlalchemy import text
    from backend.services.db import engine
    from backend.services.models import Base

    changes: list[str] = []
    errors: list[str] = []

    # 1. WAL 모드 활성 · 동시 read/write 완화 · create_all 락 회피 도움
    try:
        async with get_session() as session:
            r = await session.execute(text("PRAGMA journal_mode=WAL"))
            changes.append(f"journal_mode={r.scalar()}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"wal: {str(exc)[:150]}")

    # 2. 직접 CREATE TABLE IF NOT EXISTS · SQLAlchemy PRAGMA lookup 우회
    #    신규 모델 추가 시 여기 append (컬럼 정의는 models.py 와 일치 유지)
    direct_creates = [
        ("powderkeg_dart_corp_code", """
            CREATE TABLE IF NOT EXISTS powderkeg_dart_corp_code (
                corp_code VARCHAR(8) NOT NULL PRIMARY KEY,
                corp_name VARCHAR(200) NOT NULL,
                stock_code VARCHAR(10),
                modify_date VARCHAR(10),
                refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_dart_corp_code_stock",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_dart_corp_code_stock "
         "ON powderkeg_dart_corp_code (stock_code)"),
        # §9-3 backtest 캐시 (5년 표본 60s 초과 대응)
        ("powderkeg_backtest_report", """
            CREATE TABLE IF NOT EXISTS powderkeg_backtest_report (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(4) NOT NULL UNIQUE,
                aggregate_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                total_events INTEGER DEFAULT 0,
                valid_events INTEGER DEFAULT 0,
                validated BOOLEAN DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_backtest_report_event_type",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_backtest_report_event_type "
         "ON powderkeg_backtest_report (event_type)"),
        # P4-1 · Run 자체 기록 (2026-07-22 · v1.38)
        ("powderkeg_run", """
            CREATE TABLE IF NOT EXISTS powderkeg_run (
                run_id VARCHAR(20) NOT NULL PRIMARY KEY,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ended_at DATETIME,
                ticker_count INTEGER DEFAULT 0,
                trigger VARCHAR(16) DEFAULT 'manual',
                git_sha VARCHAR(40)
            )
        """),
        ("ix_powderkeg_run_started",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_run_started "
         "ON powderkeg_run (started_at)"),
        # P4-1 · 조건 단위 변화 로그
        ("powderkeg_run_diff", """
            CREATE TABLE IF NOT EXISTS powderkeg_run_diff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id VARCHAR(20) NOT NULL,
                ticker VARCHAR(10) NOT NULL,
                condition_key VARCHAR(64) NOT NULL,
                prev_value TEXT,
                curr_value TEXT,
                prev_status VARCHAR(16),
                curr_status VARCHAR(16),
                reason_hint VARCHAR(255),
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_run_diff_run",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_run_diff_run "
         "ON powderkeg_run_diff (run_id)"),
        ("ix_powderkeg_run_diff_ticker",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_run_diff_ticker "
         "ON powderkeg_run_diff (ticker)"),
        ("ix_powderkeg_run_diff_changed_at",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_run_diff_changed_at "
         "ON powderkeg_run_diff (changed_at)"),
        ("ix_pk_run_diff_ticker_time",
         "CREATE INDEX IF NOT EXISTS ix_pk_run_diff_ticker_time "
         "ON powderkeg_run_diff (ticker, changed_at)"),
        ("ix_pk_run_diff_cond_time",
         "CREATE INDEX IF NOT EXISTS ix_pk_run_diff_cond_time "
         "ON powderkeg_run_diff (condition_key, changed_at)"),
        # P4-5 · KRX 관리종목/거래정지 스냅샷 (2026-07-23 · v1.39)
        ("powderkeg_krx_issue", """
            CREATE TABLE IF NOT EXISTS powderkeg_krx_issue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker VARCHAR(10) NOT NULL,
                name VARCHAR(200),
                kind VARCHAR(16) NOT NULL,
                reason VARCHAR(500),
                designation_date VARCHAR(20),
                snapshot_date VARCHAR(10) NOT NULL,
                refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_krx_issue_ticker",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_krx_issue_ticker "
         "ON powderkeg_krx_issue (ticker)"),
        ("ix_powderkeg_krx_issue_snap",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_krx_issue_snap "
         "ON powderkeg_krx_issue (snapshot_date)"),
        ("ix_pk_krx_issue_ticker_kind_snap",
         "CREATE INDEX IF NOT EXISTS ix_pk_krx_issue_ticker_kind_snap "
         "ON powderkeg_krx_issue (ticker, kind, snapshot_date)"),
        # P2-1 · KIND 상장폐지 종목 스냅샷 + 백필 진행 저장 (2026-07-23 · v1.40)
        ("powderkeg_delisted_issue", """
            CREATE TABLE IF NOT EXISTS powderkeg_delisted_issue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker VARCHAR(10) NOT NULL,
                corp_name VARCHAR(200) NOT NULL,
                market VARCHAR(20),
                delisted_date VARCHAR(20),
                reason TEXT,
                note VARCHAR(200),
                is_transitional BOOLEAN DEFAULT 0,
                snapshot_date VARCHAR(10) NOT NULL,
                refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_delisted_issue_ticker",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_delisted_issue_ticker "
         "ON powderkeg_delisted_issue (ticker)"),
        ("ix_powderkeg_delisted_issue_snap",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_delisted_issue_snap "
         "ON powderkeg_delisted_issue (snapshot_date)"),
        ("ix_pk_delisted_ticker_snap",
         "CREATE INDEX IF NOT EXISTS ix_pk_delisted_ticker_snap "
         "ON powderkeg_delisted_issue (ticker, snapshot_date)"),
        ("powderkeg_delisted_backfill_progress", """
            CREATE TABLE IF NOT EXISTS powderkeg_delisted_backfill_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id VARCHAR(20) NOT NULL UNIQUE,
                last_offset INTEGER DEFAULT 0,
                total_candidates INTEGER DEFAULT 0,
                inserted INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                status VARCHAR(16) DEFAULT 'running',
                last_error TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_delisted_backfill_progress_run",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_delisted_backfill_progress_run "
         "ON powderkeg_delisted_backfill_progress (run_id)"),
    ]
    async with get_session() as session:
        for name, ddl in direct_creates:
            try:
                await session.execute(text(ddl))
                changes.append(f"create:{name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {str(exc)[:150]}")

    # 3. ALTER TABLE ADD COLUMN (기존 테이블 · schema drift)
    alter_stmts = [
        ("powderkeg_krx_snapshot", "name", "VARCHAR(100)"),
        # Phase 7-2 UI 편집 (locked/added_by/user_note)
        ("powderkeg_list", "locked", "BOOLEAN DEFAULT 0"),
        ("powderkeg_list", "added_by", "VARCHAR(10) DEFAULT 'auto'"),
        ("powderkeg_list", "user_note", "TEXT"),
    ]
    async with get_session() as session:
        for table, col, col_type in alter_stmts:
            try:
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                changes.append(f"alter:{table}.{col}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "duplicate column name" in msg.lower() or "already" in msg.lower():
                    continue
                errors.append(f"{table}.{col}: {msg[:100]}")
    return {"applied": changes, "errors": errors}


# ─── Collectors 트리거 (인증 필수 · 외부 API 호출 · 부하 유의) ─
@router.post("/collectors/ftc-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_ftc_refresh(year: int = Body(2026, embed=True)) -> dict[str, Any]:
    """공정위 대기업집단 seed → BigBusinessGroup 재적재."""
    return await refresh_from_seed(year)


@router.post("/collectors/krx-admin-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_krx_admin_refresh() -> dict[str, Any]:
    """P4-5 · KIND 관리종목·거래정지 스냅샷 refresh.

    3 요청: adminissue.do (관리종목) + tradinghaltissue.do (거래정지) + corpList.do (매핑, 하루 캐시).
    같은 (ticker, kind, snapshot_date) 조합 중복은 skip (idempotent within a day).
    """
    from backend.powderkeg.collectors.krx_admin_issue import refresh_admin_issue_snapshot
    return await refresh_admin_issue_snapshot()


@router.post("/collectors/krx-delisted-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_krx_delisted_refresh(
    from_date: Optional[str] = Body(None, embed=True, description="YYYY-MM-DD · 기본 5년 전"),
    to_date: Optional[str] = Body(None, embed=True, description="YYYY-MM-DD · 기본 오늘"),
) -> dict[str, Any]:
    """P2-1 · KIND 상장폐지 종목 리스트 refresh.

    2 요청 (KOSPI + KOSDAQ 각각) · EUC-KR HTML 파싱.
    이관성 사유(이전상장·피흡수합병·스팩 등) 자동 태그 · 재무 백필 대상 target_candidates 계산.
    """
    from backend.powderkeg.collectors.krx_delisted import refresh_delisted_snapshot
    return await refresh_delisted_snapshot(from_date=from_date, to_date=to_date)


@router.post("/collectors/dart-financials-delisted-batch", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_financials_delisted_batch(
    years: list[int] = Body([2023, 2024, 2025], embed=True),
    limit: int = Body(50, embed=True, description="배치당 최대 종목 수"),
    offset: int = Body(0, embed=True, description="재개용 offset"),
    sleep_ms: int = Body(300, embed=True, description="호출간 대기 (ms)"),
    dry_run: bool = Body(False, embed=True, description="true=집계만 · false=실 백필"),
    run_id: Optional[str] = Body(None, embed=True, description="progress 재개 시 run_id 명시 · None=신규"),
) -> dict[str, Any]:
    """P2-1 · 상폐사 재무 백필 (KIND 후보 → DART 재무 저장).

    진행 저장: PowderKegDelistedBackfillProgress.run_id upsert.
    dry_run=True 시 실 DART 호출 없이 후보 수만 리포트.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy import update as _update

    from backend.powderkeg.collectors.dart_financials import collect_delisted_financials
    from backend.powderkeg.collectors.krx_delisted import list_backfill_candidates
    from backend.services.models import PowderKegDelistedBackfillProgress

    candidates = await list_backfill_candidates()
    total = len(candidates)

    if dry_run:
        return {
            "dry_run": True,
            "total_candidates": total,
            "sample": candidates[:5],
        }

    if total == 0:
        return {"error": "candidates 비어있음 · krx-delisted-refresh 먼저 실행"}

    # progress upsert
    if run_id is None:
        _kst = _tz(_td(hours=9))
        run_id = _dt.now(tz=_kst).strftime("%Y%m%d-%H%M%SK")

    async with get_session() as session:
        prog = (await session.execute(
            select(PowderKegDelistedBackfillProgress).where(
                PowderKegDelistedBackfillProgress.run_id == run_id
            ).limit(1)
        )).scalar_one_or_none()
        if prog is None:
            prog = PowderKegDelistedBackfillProgress(
                run_id=run_id,
                last_offset=offset,
                total_candidates=total,
                status="running",
            )
            session.add(prog)
            await session.commit()

    try:
        result = await collect_delisted_financials(
            candidates, years=years, sleep_ms=sleep_ms,
            limit=limit, offset=offset,
        )
    except Exception as exc:  # noqa: BLE001
        async with get_session() as session:
            await session.execute(
                _update(PowderKegDelistedBackfillProgress)
                .where(PowderKegDelistedBackfillProgress.run_id == run_id)
                .values(status="error", last_error=str(exc)[:500])
            )
            await session.commit()
        raise

    # progress 갱신
    is_done = result["next_offset"] >= total
    async with get_session() as session:
        await session.execute(
            _update(PowderKegDelistedBackfillProgress)
            .where(PowderKegDelistedBackfillProgress.run_id == run_id)
            .values(
                last_offset=result["next_offset"],
                inserted=PowderKegDelistedBackfillProgress.inserted + result["collected"],
                errors=PowderKegDelistedBackfillProgress.errors + result["failed"],
                status="done" if is_done else "paused",
            )
        )
        await session.commit()

    return {
        "run_id": run_id,
        "status": "done" if is_done else "paused",
        **result,
    }


@router.post("/collectors/dart-financials-universe-batch", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_financials_universe_batch(
    years: list[int] = Body([2020, 2021, 2022], embed=True, description="백필 대상 사업연도"),
    report_code: str = Body("11011", embed=True, description="사업보고서 (11011) 등"),
    limit: int = Body(3000, embed=True, description="배치당 최대 종목 수"),
    offset: int = Body(0, embed=True, description="재개용 offset"),
    sleep_ms: int = Body(300, embed=True, description="호출간 대기 (ms)"),
    dry_run: bool = Body(False, embed=True, description="true=집계만 · false=실 백필"),
    run_id: Optional[str] = Body(None, embed=True, description="progress 재개 시 run_id"),
) -> dict[str, Any]:
    """P2-1b · 활성 종목(KrxMarketSnapshot 존재) 대상 사업보고서 백필.

    각 (ticker, year) 조합 · 이미 있으면 dart_financials 내부에서 skip (release_date 비교).
    PIT 층화 백테스트(P2-2)의 표본 확보를 목적으로 2020~2022 재무 확보.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy import update as _update
    import time as _time

    from backend.powderkeg.collectors.corp_codes import resolve_corp_code
    from backend.powderkeg.collectors.dart_financials import collect_financial_snapshot
    from backend.services.models import (
        KrxMarketSnapshot,
        PowderKegDelistedBackfillProgress,
    )

    # 활성 종목 로드 · 최신 스냅샷 기준 unique
    async with get_session() as session:
        latest_snap = (await session.execute(
            select(KrxMarketSnapshot.snapshot_date)
            .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1)
        )).scalar_one_or_none()
        tickers = list((await session.execute(
            select(KrxMarketSnapshot.ticker)
            .where(KrxMarketSnapshot.snapshot_date == latest_snap)
            .order_by(KrxMarketSnapshot.ticker)
        )).scalars().all())

    total = len(tickers)
    end = min(total, offset + limit)
    slice_ = tickers[offset:end]

    if dry_run:
        return {
            "dry_run": True,
            "latest_snapshot_date": latest_snap,
            "total_tickers": total,
            "slice_size": len(slice_),
            "years": years,
            "expected_calls": len(slice_) * len(years),
            "sample_tickers": slice_[:10],
        }

    # progress row (진행 저장 · 기존 delisted progress 테이블 재활용 · run_id 이름으로 구분)
    if run_id is None:
        _kst = _tz(_td(hours=9))
        run_id = _dt.now(tz=_kst).strftime("universe-%Y%m%d-%H%M%SK")

    async with get_session() as session:
        prog = (await session.execute(
            select(PowderKegDelistedBackfillProgress).where(
                PowderKegDelistedBackfillProgress.run_id == run_id
            ).limit(1)
        )).scalar_one_or_none()
        if prog is None:
            prog = PowderKegDelistedBackfillProgress(
                run_id=run_id,
                last_offset=offset,
                total_candidates=total,
                status="running",
            )
            session.add(prog)
            await session.commit()

    stats = {
        "run_id": run_id,
        "total_tickers": total,
        "processed_tickers": 0,
        "matched_corp": 0,
        "collected": 0, "empty": 0, "failed": 0,
        "next_offset": end,
    }
    t0 = _time.time()
    for ticker in slice_:
        stats["processed_tickers"] += 1
        try:
            corp_code = await resolve_corp_code(ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[universe.backfill] %s corp_code 실패 · %s", ticker, exc)
            stats["failed"] += 1
            continue
        if not corp_code:
            stats["failed"] += 1
            continue
        stats["matched_corp"] += 1
        for year in years:
            try:
                row_id = await collect_financial_snapshot(ticker, corp_code, year, report_code)
                if row_id is not None:
                    stats["collected"] += 1
                else:
                    stats["empty"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[universe.backfill] %s/%s 실패 · %s", ticker, year, exc)
                stats["failed"] += 1
            if sleep_ms > 0:
                _time.sleep(sleep_ms / 1000.0)

    stats["elapsed_sec"] = round(_time.time() - t0, 2)
    is_done = end >= total
    async with get_session() as session:
        await session.execute(
            _update(PowderKegDelistedBackfillProgress)
            .where(PowderKegDelistedBackfillProgress.run_id == run_id)
            .values(
                last_offset=end,
                inserted=PowderKegDelistedBackfillProgress.inserted + stats["collected"],
                errors=PowderKegDelistedBackfillProgress.errors + stats["failed"],
                status="done" if is_done else "paused",
            )
        )
        await session.commit()
    stats["status"] = "done" if is_done else "paused"
    return stats


@router.get("/collectors/dart-financials-delisted-progress")
async def get_delisted_backfill_progress(
    run_id: Optional[str] = Query(None, description="특정 run · None=최신"),
) -> dict[str, Any]:
    """P2-1 · 백필 진행 저장 상태 조회."""
    from backend.services.models import PowderKegDelistedBackfillProgress
    async with get_session() as session:
        if run_id is None:
            row = (await session.execute(
                select(PowderKegDelistedBackfillProgress)
                .order_by(PowderKegDelistedBackfillProgress.updated_at.desc())
                .limit(1)
            )).scalar_one_or_none()
        else:
            row = (await session.execute(
                select(PowderKegDelistedBackfillProgress).where(
                    PowderKegDelistedBackfillProgress.run_id == run_id
                ).limit(1)
            )).scalar_one_or_none()
    if row is None:
        return {"run_id": run_id, "status": "not_found"}
    return {
        "run_id": row.run_id,
        "last_offset": row.last_offset,
        "total_candidates": row.total_candidates,
        "inserted": row.inserted,
        "errors": row.errors,
        "status": row.status,
        "last_error": row.last_error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/candidates/low-pbr")
async def get_low_pbr_candidates(
    max_pbr: float = Query(0.7, description="PBR 상한"),
    min_market_cap: float = Query(30_000_000_000, description="시총 하한 (원)"),
    max_market_cap: float = Query(1_000_000_000_000_000, description="시총 상한"),
    limit: int = Query(500, ge=1, le=2000),
    market: str = Query("ALL", description="KOSPI/KOSDAQ/ALL · ALL 은 KOSPI+KOSDAQ 통합 (v1.19)"),
) -> dict[str, Any]:
    """v1.19 · 저PBR 후보 통합 · KOSPI+KOSDAQ · 리뷰어 지적 대응.

    "화약고 서식지는 KOSPI 중소형 + KOSDAQ 중형의 비재벌 현금부자 -
     정확히 수집 안 된 구간이다"

    market="ALL" 시 두 시장 모두 필터 · 저PBR 유니버스 대량 확보.
    """
    result = await _low_pbr_impl(max_pbr, min_market_cap, max_market_cap, limit, market)
    return result


@router.get("/candidates/kosdaq-low-pbr")
async def get_kosdaq_low_pbr_candidates(
    max_pbr: float = Query(0.7, description="PBR 상한"),
    min_market_cap: float = Query(30_000_000_000, description="시총 하한 (원)"),
    max_market_cap: float = Query(1_000_000_000_000_000, description="시총 상한"),
    limit: int = Query(100, ge=1, le=500),
    market: str = Query("KOSDAQ", description="KOSPI/KOSDAQ · KOSDAQ 은 FDR PBR 결측 다수"),
) -> dict[str, Any]:
    """KRX 스냅샷 · FinancialSnapshot 조인 · 저PBR 후보 종목 리스트.

    PBR = market_cap / total_equity 자체 계산 (FDR PBR 컬럼 결측 대응).
    FinancialSnapshot 있는 종목만 pre-filter · 유니버스 확대 실용.
    """
    return await _low_pbr_impl(max_pbr, min_market_cap, max_market_cap, limit, market)


async def _low_pbr_impl(
    max_pbr: float, min_market_cap: float, max_market_cap: float,
    limit: int, market: str,
) -> dict[str, Any]:
    """공통 · 저PBR 후보 조회 (KOSPI/KOSDAQ/ALL)."""
    from backend.services.models import FinancialSnapshot, KrxMarketSnapshot
    async with get_session() as session:
        latest_date = (await session.execute(
            select(KrxMarketSnapshot.snapshot_date)
            .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1)
        )).scalar_one_or_none()
        if not latest_date:
            return {"count": 0, "items": []}

        # v1.19 · market="ALL" 지원 · KOSPI+KOSDAQ 통합
        where_clauses = [
            KrxMarketSnapshot.snapshot_date == latest_date,
            KrxMarketSnapshot.market_cap.is_not(None),
            KrxMarketSnapshot.market_cap >= min_market_cap,
            KrxMarketSnapshot.market_cap <= max_market_cap,
        ]
        if market.upper() != "ALL":
            where_clauses.append(KrxMarketSnapshot.market == market)
        # ALL 시 · 자동으로 필터 없음 · KOSPI + KOSDAQ 모두 포함

        stmt = (
            select(KrxMarketSnapshot)
            .where(*where_clauses)
            .order_by(KrxMarketSnapshot.market_cap.desc())
            .limit(2000 if market.upper() == "ALL" else 500)
        )
        krx_rows = (await session.execute(stmt)).scalars().all()

        # 각 종목 · FinancialSnapshot.total_equity 조인 · PBR 계산
        candidates: list[dict] = []
        for r in krx_rows:
            fin_stmt = (
                select(FinancialSnapshot.total_equity)
                .where(
                    FinancialSnapshot.ticker == r.ticker,
                    FinancialSnapshot.report_code == "11011",
                )
                .order_by(FinancialSnapshot.reference_date.desc())
                .limit(1)
            )
            equity = (await session.execute(fin_stmt)).scalar_one_or_none()
            pbr = None
            if r.pbr is not None:
                pbr = r.pbr
            elif equity and equity > 0:
                pbr = r.market_cap / equity
            if pbr is None or pbr <= 0 or pbr >= max_pbr:
                continue
            candidates.append({
                "ticker": r.ticker, "name": r.name, "pbr": round(pbr, 3),
                "market_cap": r.market_cap, "close_price": r.close_price,
                "pbr_source": "krx" if r.pbr is not None else "computed",
            })
            if len(candidates) >= limit:
                break

    return {
        "count": len(candidates),
        "snapshot_date": latest_date,
        "filter": {"market": market, "max_pbr": max_pbr, "min_market_cap": min_market_cap, "max_market_cap": max_market_cap},
        "items": candidates,
    }


@router.get("/big-biz")
async def get_big_biz(year: int = Query(2026)) -> dict[str, Any]:
    """대기업집단 목록 조회 (디버그·UI 검증용)."""
    items = await list_big_biz(year)
    return {"year": year, "count": len(items), "items": items}


@router.post("/collectors/krx-snapshot", dependencies=[Depends(require_sniper_token)])
async def trigger_krx_snapshot(
    tickers: Optional[list[str]] = Body(None, embed=True),
    include_adv60: bool = Body(False, embed=True),
) -> dict[str, Any]:
    """KRX 시장 스냅샷 (KOSPI+KOSDAQ 전체 또는 tickers 지정)."""
    return await collect_market_snapshot(
        tickers=set(tickers) if tickers else None,
        include_adv60=include_adv60,
    )


@router.post("/collectors/dart-financials", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_financials(
    tickers: Optional[list[str]] = Body(None, embed=True),
    targets: Optional[list[dict[str, str]]] = Body(None, embed=True),
    bsns_year: int = Body(2026, embed=True),
    reprt_code: str = Body("11011", embed=True),
) -> dict[str, Any]:
    """DART 재무제표 batch 수집.

    입력 방식 (하나만):
      tickers: ["005930", "000660", ...] · corp_code 자동 해결 (DartCorpCodeMap 필요)
      targets: [{"ticker": ..., "corp_code": ...}, ...] · 직접 지정

    reprt_code: 11011(사업)·11012(반기)·11013(1분기)·11014(3분기)
    """
    pairs = await _resolve_pairs(tickers, targets)
    if not pairs:
        raise HTTPException(status_code=400, detail="no valid (ticker,corp_code) resolved")
    return await dart_collect_batch(pairs, bsns_year=bsns_year, reprt_code=reprt_code)


async def _resolve_pairs(
    tickers: Optional[list[str]], targets: Optional[list[dict[str, str]]],
) -> list[tuple[str, str]]:
    """tickers → corp_codes 자동 해결 · targets 직접 지정 · 하나 이상 필수."""
    if targets:
        return [(t["ticker"], t["corp_code"]) for t in targets
                if t.get("ticker") and t.get("corp_code")]
    if tickers:
        cc_map = await resolve_many(tickers)
        return [(tk, cc_map[tk]) for tk in tickers if cc_map.get(tk)]
    return []


@router.post("/collectors/dart-shareholders", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_shareholders(
    tickers: Optional[list[str]] = Body(None, embed=True),
    targets: Optional[list[dict[str, str]]] = Body(None, embed=True),
    bsns_year: int = Body(2025, embed=True),
    reprt_code: str = Body("11011", embed=True),
) -> dict[str, Any]:
    """DART 최대주주 현황 + 자기주식 batch.

    입력 방식 (하나만):
      tickers: 티커 리스트 · corp_code 자동 해결
      targets: 직접 지정
    """
    pairs = await _resolve_pairs(tickers, targets)
    if not pairs:
        raise HTTPException(status_code=400, detail="no valid (ticker,corp_code) resolved")
    return await sh_collect_batch(pairs, bsns_year=bsns_year, reprt_code=reprt_code)


@router.post("/collectors/events-poll", dependencies=[Depends(require_sniper_token)])
async def trigger_events_poll(
    lookback_days: int = Body(1, embed=True),
    watched_tickers: Optional[list[str]] = Body(None, embed=True),
) -> dict[str, Any]:
    """DART 공시 이벤트 폴링 · Type A/B 분류 후 PowderKegEvent 저장.

    watched_tickers None = 모든 매칭 저장 · list = 감시 대상만.
    """
    return await poll_powderkeg_events(
        lookback_days=lookback_days,
        watched_tickers=set(watched_tickers) if watched_tickers else None,
    )


@router.post("/admin/holding-expiry-run", dependencies=[Depends(require_sniper_token)])
async def trigger_holding_expiry() -> dict[str, Any]:
    """수동 실행 · powderkeg_holding_expiry 잡 (§7-5 12개월 재평가).

    스케줄러 잡 (매일 08:00 KST) 과 동일 로직 · 검증·수동 트리거 용도.
    """
    from backend.powderkeg.scheduler import holding_expiry_job
    return await holding_expiry_job()


@router.post("/backtest/stratified/{event_type}", dependencies=[Depends(require_sniper_token)])
async def trigger_stratified_backtest(
    event_type: str,
    stratum: str = Body("powderkeg_passed", embed=True),
) -> dict[str, Any]:
    """화약고 층화 백테스트 · v1.10 (§10-5 층화 · 리뷰어 지적 대응).

    stratum:
      · powderkeg_passed · 화약고 리스트 status=passed 종목만 (교집합 검증)
      · all              · 전체 시장 (대조군)

    결과는 event_type__stratum 키로 캐시 저장 · GET /report/{event_type}__{stratum} 로 조회.
    """
    from backend.powderkeg.backtest import run_stratified_backtest
    return await run_stratified_backtest(event_type=event_type, stratum=stratum)


@router.post("/collectors/news-poll", dependencies=[Depends(require_sniper_token)])
async def trigger_news_poll(
    lookback_hours: int = Body(24, embed=True),
    only_watched: bool = Body(True, embed=True),
) -> dict[str, Any]:
    """뉴스 크롤링 · A1/A2/A6 · 5 RSS 소스 (§7-1-4).

    only_watched=True (기본) · 화약고 리스트 종목만 저장 (스팸 방지).
    """
    from backend.powderkeg.collectors.news_crawler import poll_powderkeg_news
    return await poll_powderkeg_news(lookback_hours=lookback_hours, only_watched=only_watched)


@router.post("/collectors/events-backfill", dependencies=[Depends(require_sniper_token)])
async def trigger_events_backfill(
    start_date: str = Body(..., embed=True, description="YYYY-MM-DD"),
    end_date: str = Body(..., embed=True, description="YYYY-MM-DD"),
    chunk_days: int = Body(30, embed=True, description="청크 크기 (일)"),
    sleep_between_chunks: float = Body(1.0, embed=True),
    watched_tickers: Optional[list[str]] = Body(None, embed=True),
) -> dict[str, Any]:
    """장기 아카이브 backfill · §7-4 5년 백테스트 표본 확보.

    예시: start_date=2021-07-16, end_date=2026-07-15 · 5년 backfill.
    청크당 DART 4 pblntf_ty 조회 · sleep 로 rate limit 완화.
    """
    from datetime import date as _date
    try:
        sd = _date.fromisoformat(start_date)
        ed = _date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date format: {exc}")
    if sd > ed:
        raise HTTPException(status_code=400, detail="start_date > end_date")
    return await backfill_powderkeg_events(
        start_date=sd, end_date=ed,
        chunk_days=chunk_days,
        sleep_between_chunks=sleep_between_chunks,
        watched_tickers=set(watched_tickers) if watched_tickers else None,
    )


@router.post("/screener/run", dependencies=[Depends(require_sniper_token)])
async def trigger_screener(
    tickers: list[str] = Body(..., embed=True),
    year: int = Body(2026, embed=True),
) -> dict[str, Any]:
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers required")
    return await run_screener(tickers, year=year)


@router.post("/backtest/{event_type}", dependencies=[Depends(require_sniper_token)])
async def trigger_backtest(event_type: str) -> dict[str, Any]:
    """이벤트 타입 백테스트 실행 + validated 승격 (게이트 통과 시)."""
    return await run_backtest_for_event_type(event_type)


@router.post("/backtest/{event_type}/stratified", dependencies=[Depends(require_sniper_token)])
async def trigger_stratified_backtest(
    event_type: str,
    stratum: str = Body("powderkeg_pit", embed=True,
                        description="powderkeg_passed (오늘 리스트) · powderkeg_pit (P2-2 · 이벤트 시점 재평가) · all (전체 시장)"),
) -> dict[str, Any]:
    """P2-2 · 화약고 층화 백테스트 트리거.

    stratum:
      · powderkeg_pit    · 각 이벤트 release_date 시점 화약고 재평가 (편향 최소)
      · powderkeg_passed · 오늘의 화약고 리스트 (기존 · 대조군 · 편향 있음)
      · all              · 전체 시장 (전 종목)
    """
    return await run_stratified_backtest(event_type, stratum=stratum)


@router.post("/triggers/process", dependencies=[Depends(require_sniper_token)])
async def trigger_process_pending() -> dict[str, Any]:
    """미처리 이벤트 batch · Type A/B 액션 실행."""
    return await process_pending_events()


@router.post("/ticket", dependencies=[Depends(require_sniper_token)])
async def create_ticket_route(
    event_id: int = Body(...),
    ticker: str = Body(...),
    proposed_qty: int = Body(...),
    invalidation_price: float = Body(...),
    invalidation_logic: str = Body(...),
    total_capital_krw: float = Body(...),
    per_ticker_krw: float = Body(...),
    proposed_price: Optional[float] = Body(None),
    holding_days_max: int = Body(365),
) -> dict[str, Any]:
    req = TicketCreateRequest(
        event_id=event_id, ticker=ticker,
        proposed_qty=proposed_qty,
        invalidation_price=invalidation_price,
        invalidation_logic=invalidation_logic,
        proposed_price=proposed_price,
        holding_days_max=holding_days_max,
    )
    try:
        tid = await create_ticket(req, total_capital_krw, per_ticker_krw)
    except TicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": tid, "status": "pending"}


@router.patch("/ticket/{ticket_id}/approve", dependencies=[Depends(require_sniper_token)])
async def approve_route(ticket_id: int, approver: str = Body(..., embed=True)) -> dict[str, Any]:
    ok = await approve_ticket(ticket_id, approver)
    if not ok:
        raise HTTPException(status_code=400, detail="approve_failed(status_not_pending)")
    return {"id": ticket_id, "status": "approved"}


@router.patch("/ticket/{ticket_id}/reject", dependencies=[Depends(require_sniper_token)])
async def reject_route(ticket_id: int, reason: str = Body(..., embed=True)) -> dict[str, Any]:
    ok = await reject_ticket(ticket_id, reason)
    if not ok:
        raise HTTPException(status_code=400, detail="reject_failed(status_not_pending)")
    return {"id": ticket_id, "status": "rejected"}
