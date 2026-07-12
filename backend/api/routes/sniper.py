"""Sniper API 라우트 · Sprint 1 T44.

라우트 분류:
1. 조회 (인증 없음 · GET · 정보 노출만)
   - GET /params
   - GET /universe
   - GET /candidates
   - GET /signals/recent
   - GET /status
2. 편집·실행 (X-API-Token + SNIPER_LIVE_ENABLED 필수)
   - PUT /params
   - POST /universe/refresh
   - POST /entry
   - POST /exit/{signal_id}

보안: `feedback_sniper_security_and_flexibility`
계획서: `docs/plans/sniper/00-sprint1-plan.md` §2-1
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

from backend.api.auth import (
    is_sniper_live_enabled,
    require_sniper_live_token,
    require_sniper_token,
)
from backend.discovery.live_tape.entry import execute_entry
from backend.discovery.live_tape.params import (
    SniperParams,
    get_sniper_params,
    get_sniper_params_store,
)
from backend.discovery.live_tape.scoring import is_candidate, score_ticker
from backend.discovery.live_tape.universe import (
    list_universe,
    refresh_universe,
    universe_size,
)
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.kill_switch import get_kill_switch
from backend.services.db import get_session
from backend.services.models import SniperSignal

logger = logging.getLogger(__name__)
router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 조회 (인증 없음)
# ═══════════════════════════════════════════════════════════════
@router.get("/status")
async def sniper_status():
    """전역 상태 · UI 상단 표시용."""
    params = get_sniper_params()
    ks = get_kill_switch().status()
    size = await universe_size()
    return {
        "live_enabled": is_sniper_live_enabled(),
        "sniper_enabled": params.enabled,
        "kill_switch_active": ks.active,
        "universe_size": size,
        "seed_cap_krw": params.seed_cap_krw,
        "per_order_krw": params.per_order_krw,
        "max_concurrent_positions": params.max_concurrent_positions,
        "trailing_giveback_pct": params.trailing_giveback_pct,
        "hard_stop_loss_pct": params.hard_stop_loss_pct,
        "active_window_kst": {
            "start": params.active_start_kst,
            "end": params.active_end_kst,
        },
        "force_close_enabled": params.force_close_enabled,
        "force_close_kst": params.force_close_kst,
    }


@router.get("/params")
async def get_params():
    return asdict(get_sniper_params())


@router.get("/universe")
async def get_universe(
    squeeze_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
):
    return {
        "size": await universe_size(),
        "items": await list_universe(squeeze_only=squeeze_only, limit=limit),
    }


@router.get("/signals/recent")
async def recent_signals(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=500),
):
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    async with get_session() as session:
        stmt = (
            select(SniperSignal)
            .where(SniperSignal.detected_at >= since)
            .order_by(SniperSignal.detected_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "tape_score": r.tape_score,
            "rank_velocity": r.rank_velocity,
            "trades_intensity": r.trades_intensity,
            "orderbook_imbalance": r.orderbook_imbalance,
            "entry_order_uuid": r.entry_order_uuid,
            "entry_price": r.entry_price,
            "exit_order_uuid": r.exit_order_uuid,
            "exit_price": r.exit_price,
            "peak_price": r.peak_price,
            "pnl_pct": r.pnl_pct,
            "reason": r.reason,
        }
        for r in rows
    ]


@router.get("/candidates")
async def scan_candidates(top_n: int = Query(10, ge=1, le=50)):
    """유니버스 상위 종목 대상 즉시 스캔 · 인증 없음 (수동 확인용).

    실주문 트리거 아님. 결과만 반환.
    """
    universe = await list_universe(limit=top_n)
    results = []
    for u in universe:
        sig = await score_ticker(u["ticker"])
        if sig is None:
            continue
        ok, reason = is_candidate(sig)
        results.append(
            {
                "ticker": sig.ticker,
                "name": u.get("name"),
                "tape_score": sig.tape_score,
                "rank_velocity_score": sig.rank_velocity_score,
                "trades_intensity_score": sig.trades_intensity_score,
                "orderbook_score": sig.orderbook_score,
                "last_price": sig.last_price,
                "return_pct": sig.return_pct,
                "candidate": ok,
                "reject_reason": reason,
            }
        )
    results.sort(key=lambda x: -x["tape_score"])
    return results


# ═══════════════════════════════════════════════════════════════
# 편집·실행 (X-API-Token 필수)
# ═══════════════════════════════════════════════════════════════
@router.put("/params", dependencies=[Depends(require_sniper_token)])
async def put_params(payload: dict = Body(...)):
    """SniperParams 부분 업데이트. 인증 필수."""
    try:
        new_params = get_sniper_params_store().patch(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("sniper params updated · keys=%s", list(payload.keys()))
    return {"ok": True, "params": asdict(new_params)}


@router.post("/universe/refresh", dependencies=[Depends(require_sniper_token)])
async def universe_refresh():
    """수동 유니버스 재싱크. 인증 필수 (Toss/pykrx 부하 방지)."""
    try:
        stats = await refresh_universe()
    except Exception as exc:  # noqa: BLE001
        logger.exception("universe refresh 실패")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return stats


@router.post("/entry", dependencies=[Depends(require_sniper_live_token)])
async def manual_entry(
    ticker: str = Body(..., embed=True),
    broker: str = Body("paper", embed=True),
):
    """수동 진입 · 감사 대상 candidate 강제 진입.

    T44 검증용 · T50 오케스트레이터가 자동 호출도 이 경로 사용.
    """
    signal = await score_ticker(ticker)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"score 산출 실패 · {ticker}")

    ok, reason = is_candidate(signal)
    if not ok:
        logger.info("manual entry · candidate 미충족 · %s · %s", ticker, reason)

    # broker 선택
    if broker.lower() == "toss":
        from backend.execution.brokers.toss_adapter import TossAdapter
        om = TossAdapter()
    else:
        om = PaperAdapter()

    result = await execute_entry(signal, om)
    return {
        "ok": result.ok,
        "reason": result.reason,
        "order_uuid": result.order_uuid,
        "broker_order_id": result.broker_order_id,
        "filled_qty": result.filled_qty,
        "entry_price": result.entry_price,
        "sniper_signal_id": result.sniper_signal_id,
        "candidate_passed": ok,
        "candidate_reject_reason": reason,
    }
