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
from backend.powderkeg.backtest import run_backtest_for_event_type
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
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
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

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "ticker": r.ticker, "name": r.name,
                "status": r.status, "net_cash_ratio": r.net_cash_ratio,
                "piotroski_f_score": r.piotroski_f_score,
                "owner_pct": r.owner_pct, "treasury_pct": r.treasury_pct,
                "pbr": r.pbr, "dividend_payout": r.dividend_payout,
                "conditions": json.loads(r.conditions_json) if r.conditions_json else None,
                "reject_reasons": r.reject_reasons,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
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


@router.get("/report/{event_type}")
async def get_report(event_type: str) -> dict[str, Any]:
    """탭 3 · 백테스트 리포트 (저장 캐시 없음 · 매 호출 재계산 · v2 캐시)."""
    report = await run_backtest_for_event_type(event_type)
    report["disclaimer"] = DISCLAIMER
    return report


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
