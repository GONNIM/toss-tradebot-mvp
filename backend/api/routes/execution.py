"""Execution Layer API 라우트 — v2 트랙 C Phase 1.

엔드포인트:
- GET  /api/v1/execution/status              전역 상태 (enabled · broker · kill-switch)
- GET  /api/v1/execution/kill-switch/status  Kill Switch 상태 조회
- POST /api/v1/execution/kill-switch         수동 발동
- DELETE /api/v1/execution/kill-switch       수동 해제
- GET  /api/v1/execution/params              파라미터 override 전체 조회
- PUT  /api/v1/execution/params              파라미터 저장 (즉시 반영)
- GET  /api/v1/execution/paper/state         Paper 어댑터 스냅샷
- POST /api/v1/execution/paper/resync        Toss API 재싱크
- POST /api/v1/execution/paper/reset         수동 자본 리셋
- GET  /api/v1/execution/audit               최근 감사 로그
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from backend.execution.audit import list_recent_audits
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.kill_switch import get_kill_switch
from backend.execution.params import (
    ExecutionParams,
    RiskBudget,
    ThresholdSet,
    get_params_store,
)
from backend.execution.signal_router import get_signal_router, reset_signal_router
from backend.execution.models import BrokerKind

logger = logging.getLogger(__name__)
router = APIRouter()


# 프로세스 lifetime PaperAdapter (라우트에서 재사용)
_paper: Optional[PaperAdapter] = None


def _get_paper() -> PaperAdapter:
    global _paper
    if _paper is None:
        _paper = PaperAdapter()
    return _paper


def _reset_paper_cache() -> None:
    """리셋·재싱크 후 Router의 어댑터 캐시도 갱신."""
    global _paper
    _paper = None
    reset_signal_router()


# ═══════════════════════════════════════════════════════════════
# 전역 상태
# ═══════════════════════════════════════════════════════════════
@router.get("/status")
async def get_status():
    ks = get_kill_switch().status()
    return {
        "execution_enabled": os.environ.get("EXECUTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        "broker": os.environ.get("EXECUTION_BROKER", "paper"),
        "kill_switch": {
            "active": ks.active,
            "reason": ks.reason,
            "activated_at": ks.activated_at.isoformat() if ks.activated_at else None,
            "activated_by": ks.activated_by,
        },
    }


# ═══════════════════════════════════════════════════════════════
# Kill Switch
# ═══════════════════════════════════════════════════════════════
@router.get("/kill-switch/status")
async def kill_switch_status():
    s = get_kill_switch().status()
    return {
        "active": s.active,
        "reason": s.reason,
        "activated_at": s.activated_at.isoformat() if s.activated_at else None,
        "activated_by": s.activated_by,
        "deactivated_at": s.deactivated_at.isoformat() if s.deactivated_at else None,
        "deactivated_by": s.deactivated_by,
    }


@router.post("/kill-switch")
async def kill_switch_activate(
    reason: str = Body(..., embed=True),
    actor: str = Body("user:manual", embed=True),
):
    s = get_kill_switch().activate(reason=reason, actor=actor)
    return {"active": s.active, "reason": s.reason, "activated_by": s.activated_by}


@router.delete("/kill-switch")
async def kill_switch_deactivate(actor: str = Query("user:manual")):
    s = get_kill_switch().deactivate(actor=actor)
    return {"active": s.active, "deactivated_by": s.deactivated_by}


# ═══════════════════════════════════════════════════════════════
# Execution Params (TP · SL · Trailing · Risk Budget)
# ═══════════════════════════════════════════════════════════════
def _ts_to_dict(t: ThresholdSet) -> dict:
    return {
        "take_profit_pct": t.take_profit_pct,
        "stop_loss_pct": t.stop_loss_pct,
        "trailing_arm_pct": t.trailing_arm_pct,
        "trailing_giveback_pct": t.trailing_giveback_pct,
    }


def _rb_to_dict(rb: RiskBudget) -> dict:
    return {
        "per_ticker_max_pct": rb.per_ticker_max_pct,
        "daily_loss_limit": rb.daily_loss_limit,
        "ticker_dd_limit": rb.ticker_dd_limit,
    }


def _dict_to_ts(d: Optional[dict]) -> ThresholdSet:
    d = d or {}
    return ThresholdSet(
        take_profit_pct=d.get("take_profit_pct"),
        stop_loss_pct=d.get("stop_loss_pct"),
        trailing_arm_pct=d.get("trailing_arm_pct"),
        trailing_giveback_pct=d.get("trailing_giveback_pct"),
    )


@router.get("/params")
async def get_params():
    params = get_params_store().get()
    return {
        "global": _ts_to_dict(params.global_),
        "risk_budget": _rb_to_dict(params.risk_budget),
        "tickers": {k: _ts_to_dict(v) for k, v in params.tickers.items()},
        "signals": {k: _ts_to_dict(v) for k, v in params.signals.items()},
    }


@router.put("/params")
async def put_params(payload: dict = Body(...)):
    """전체 파라미터 저장 (부분 갱신 아님). PUT 이므로 지정된 값이 전체."""
    try:
        params = ExecutionParams(
            global_=_dict_to_ts(payload.get("global")),
            risk_budget=RiskBudget(
                **{
                    "per_ticker_max_pct": (payload.get("risk_budget") or {}).get(
                        "per_ticker_max_pct", 0.10
                    ),
                    "daily_loss_limit": (payload.get("risk_budget") or {}).get(
                        "daily_loss_limit", -0.03
                    ),
                    "ticker_dd_limit": (payload.get("risk_budget") or {}).get(
                        "ticker_dd_limit", -0.05
                    ),
                }
            ),
            tickers={k: _dict_to_ts(v) for k, v in (payload.get("tickers") or {}).items()},
            signals={k: _dict_to_ts(v) for k, v in (payload.get("signals") or {}).items()},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"파라미터 파싱 실패: {exc}") from exc
    get_params_store().save(params)
    return {"ok": True, "saved": True}


# ═══════════════════════════════════════════════════════════════
# Paper Adapter
# ═══════════════════════════════════════════════════════════════
@router.get("/paper/state")
async def paper_state():
    return _get_paper().snapshot_state()


@router.post("/paper/resync")
async def paper_resync():
    try:
        state = _get_paper().resync_from_toss()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Toss 재싱크 실패: {exc}") from exc
    _reset_paper_cache()
    return {"ok": True, "synced_from": state.synced_from, "synced_at": state.synced_at}


@router.post("/paper/reset")
async def paper_reset(cash_krw: Optional[float] = Body(None, embed=True)):
    state = _get_paper().reset(cash_krw=cash_krw)
    _reset_paper_cache()
    return {"ok": True, "cash_krw": state.cash_krw, "synced_from": state.synced_from}


# ═══════════════════════════════════════════════════════════════
# Audit
# ═══════════════════════════════════════════════════════════════
@router.get("/audit")
async def audit_list(
    ticker: Optional[str] = Query(None),
    broker: Optional[str] = Query(None),
    signal_source: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    bk = None
    if broker:
        try:
            bk = BrokerKind(broker.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"unknown broker={broker}")
    rows = await list_recent_audits(
        ticker=ticker, broker_kind=bk, signal_source=signal_source, limit=limit
    )
    return [
        {
            "order_uuid": r.order_uuid,
            "broker_kind": r.broker_kind,
            "broker_order_id": r.broker_order_id,
            "ticker": r.ticker,
            "side": r.side,
            "order_type": r.order_type,
            "qty": r.qty,
            "price": r.price,
            "signal_source": r.signal_source,
            "signal_id": r.signal_id,
            "status": r.status,
            "filled_qty": r.filled_qty,
            "avg_fill_price": r.avg_fill_price,
            "total_fee": r.total_fee,
            "error_code": r.error_code,
            "error_message": r.error_message,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
