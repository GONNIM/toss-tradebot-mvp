"""계획 실행기 API · 1116-01 (계획서 3 · 4절).

화면 서버(tradebot-api)는 토스 주문 · 조건주문 API 를 부르지 않는다. DB 만 고치고, 토스에 닿는 일은
`plan_request` 표에 남겨 실행기(tradebot-cron)가 처리한다. 아래 DB 전용 엔진의 브로커는 부르면 바로 오류가 난다.

인증 (계획서 3절)
- 조회: 관리자(쿠키 · 헤더) · 로그아웃은 모두 401
- 새 계획 · 초안 수정 · 계획 정지 · 인수 취소 · 시간 손절 중지: 쿠키 · 헤더 (쿠키일 때 Origin 검사)
- 스위치 · 확인 코드 요청 · 승인 · 인수 · 재개: 쿠키만 + Origin (실거래 켜기 · 실전/시험 승인 · 인수 · 재개는 텔레그램 확인 코드)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.auth import require_plan_cookie, require_plan_write, require_sniper_token
from backend.execution.exceptions import ExecutionError
from backend.execution.plan import heartbeat, sizing, state
from backend.execution.plan import switches as sw
from backend.execution.plan.brokers import DirectionGate, RawBroker
from backend.execution.plan.engine import PlanEngine, approval_values, params_of
from backend.execution.plan.models import (
    Plan, PlanEvent, PlanExecutorHeartbeat, PlanLeg, PlanRequest, PlanSwitchAudit, PlanSellReservation,
)
from backend.services.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


class _NoBroker(RawBroker):
    """화면 서버용 · 토스를 부르면 바로 오류. (DB 만 고치는 엔진 메서드만 쓴다)"""

    mode = "none"

    def __getattribute__(self, name):  # noqa: D105
        if name.startswith("_") or name == "mode":
            return object.__getattribute__(self, name)

        async def _boom(*a, **k):
            raise ExecutionError("화면 서버는 토스를 부르지 않습니다")

        return _boom


async def _noop_notify(level: str, title: str, body: str, category: str) -> None:
    return None


def _engine() -> PlanEngine:
    return PlanEngine(DirectionGate(_NoBroker()), notify=_noop_notify)


def _kill_state():
    from backend.execution.plan.runner import _kill_state as ks

    return ks()


async def _send_code(title: str, body: str) -> bool:
    """확인 코드를 텔레그램 ⑨ 범주로 즉시 보낸다 (알림 설정 · 하루 요약 무시 · 기록에는 제목만)."""
    from backend.services.notifier import TelegramNotifier

    return await TelegramNotifier().send_immediate(title, body)


async def _alert(level: str, title: str, body: str) -> None:
    from backend.services.notifier import TelegramNotifier

    n = TelegramNotifier()
    try:
        if level == "critical":
            await n.send_critical(title, body, category="execution")
        else:
            await n.send_warning(title, body, category="execution")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plans] 알림 실패 · %s", exc.__class__.__name__)


def _confirm_http(exc: sw.ConfirmError) -> HTTPException:
    code = 423 if exc.reason == "locked" else 400
    return HTTPException(status_code=code, detail={"reason": exc.reason, "message": exc.message})


async def _confirm_fail(s, exc: sw.ConfirmError) -> HTTPException:
    """확인 코드 거부는 세션을 되돌리기 전에 먼저 저장한다 — 틀린 횟수 · 실패 누적 · 무효 표시가 사라지면 잠금이 안 걸린다."""
    await s.commit()
    return _confirm_http(exc)


def _plan_json(p: Plan) -> dict:
    return {
        "id": p.id, "mode": p.mode, "source": p.source, "symbol": p.symbol, "state": p.state,
        "revision": p.revision, "halted_reason": p.halted_reason, "approved_by": p.approved_by,
        "avg_price": p.avg_price, "peak_price": p.peak_price, "timestop_stage": p.timestop_stage,
        "params": params_of(p), "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def _get_plan(s, plan_id: int) -> Plan:
    p = await s.get(Plan, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="계획을 찾을 수 없습니다")
    return p


# ─── 조회 (관리자 · 쿠키 또는 헤더) ───────────────────────────────

@router.get("")
async def list_plans(_: str = Depends(require_sniper_token)) -> dict:
    async with get_session() as s:
        rows = await s.scalars(select(Plan).order_by(Plan.id.desc()).limit(200))
        return {"plans": [_plan_json(p) for p in rows]}


@router.get("/executor/status")
async def executor_status(_: str = Depends(require_sniper_token)) -> dict:
    sws = sw.read_switches()
    killed, sell_allowed = _kill_state()
    async with get_session() as s:
        age = await heartbeat.age_seconds(s)
        row = await s.get(PlanExecutorHeartbeat, 1)
        last = (await s.scalar(select(PlanSwitchAudit).order_by(PlanSwitchAudit.id.desc()).limit(1)))
        return {
            "switches": {"live": sws["live"], "paper": sws["paper"]},
            "last_change": {"actor": last.actor, "ts": last.ts.isoformat(), "reason": last.reason,
                            "switch": last.switch, "new": last.new} if last else None,
            "kill_switch": {"active": killed, "sell_allowed": sell_allowed},
            "heartbeat_age_sec": age,
            "ws_status": row.ws_status if row else None,
            "last_resync_at": row.last_resync_at.isoformat() if row and row.last_resync_at else None,
        }


@router.get("/{plan_id:int}")
async def plan_detail(plan_id: int, _: str = Depends(require_sniper_token)) -> dict:
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        legs = list(await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == p.id).order_by(PlanLeg.id)))
        events = list(await s.scalars(select(PlanEvent).where(PlanEvent.plan_id == p.id).order_by(PlanEvent.id.desc()).limit(100)))
        base = await sizing.plan_qty(s, p)
        acc = await sizing.accepted_sell(s, p.id)
        live = await sizing.live_sl_legs(s, p.id)
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in live])
        return {
            "plan": _plan_json(p),
            "approval_values": approval_values(p),
            "content_hash": p.content_hash[:12],
            "legs": [{"id": l.id, "role": l.role, "seq": l.seq, "kind": l.kind, "qty": l.qty, "watch": l.watch_price,
                      "order": l.order_price, "status": l.status, "tag": l.tag} for l in legs],
            "events": [{"ts": e.ts.isoformat(), "kind": e.kind, "detail": e.detail} for e in events],
            "invariant": {"status": rep.status, "plan_qty": base, "accepted_sell": acc, "sl_sum": rep.sl_sum,
                          "target": rep.target},
        }


# ─── 새 계획 · 초안 수정 · 정지 (쿠키 · 헤더) ──────────────────────────

class PlanCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    mode: str = Field(..., pattern="^(paper|live|test)$")
    source: str = Field("manual", pattern="^(manual|adopt)$")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def create_plan(body: PlanCreate, src: str = Depends(require_plan_write)) -> dict:
    eng = _engine()
    try:
        async with get_session() as s:
            p = await eng.create_draft(s, symbol=body.symbol.upper(), mode=body.mode, params=body.params, source=body.source)
            return {"plan": _plan_json(p)}
    except state.TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class PlanEdit(BaseModel):
    values: dict[str, Any]


@router.patch("/{plan_id:int}")
async def edit_plan(plan_id: int, body: PlanEdit, src: str = Depends(require_plan_write)) -> dict:
    eng = _engine()
    try:
        async with get_session() as s:
            p = await _get_plan(s, plan_id)
            await eng.update_draft(s, p, body.values)
            return {"plan": _plan_json(p)}
    except state.TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


async def _queue(s, plan: Plan, action: str, who: str) -> PlanRequest:
    req = PlanRequest(plan_id=plan.id, action=action, requested_by=who)
    s.add(req)
    await s.flush()
    return req


@router.post("/{plan_id:int}/stop")
async def stop_plan(plan_id: int, src: str = Depends(require_plan_write)) -> dict:
    """계획 정지 · 헤더도 허용 · 새 등록 · 매수를 멈춘다(HALTED) · 대기 매수 취소는 실행기가 · 매도 다리는 지우지 않는다."""
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        stopped = await state.halt(s, p, "계획 정지 (화면)")
        await _queue(s, p, "stop", src)
        return {"halted": stopped, "plan": _plan_json(p)}


@router.post("/{plan_id:int}/adopt-cancel")
async def adopt_cancel(plan_id: int, src: str = Depends(require_plan_write)) -> dict:
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        if p.state != state.ADOPT_PENDING:
            raise HTTPException(status_code=409, detail="인수 대기 상태가 아닙니다")
        req = await _queue(s, p, "adopt_cancel", src)
        return {"queued": req.id}


@router.post("/{plan_id:int}/timestop-stop")
async def timestop_stop(plan_id: int, src: str = Depends(require_plan_write)) -> dict:
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        req = await _queue(s, p, "timestop_stop", src)
        return {"queued": req.id}


# ─── 확인 코드 요청 · 승인 · 인수 · 재개 (쿠키만 + Origin) ─────────────────

class ConfirmChallengeReq(BaseModel):
    action: str = Field(..., pattern="^(approve|adopt|resume)$")
    plan_id: int


@router.post("/confirm/challenge")
async def confirm_challenge(body: ConfirmChallengeReq, src: str = Depends(require_plan_cookie)) -> dict:
    async with get_session() as s:
        p = await _get_plan(s, body.plan_id)
        if p.mode == "paper":
            raise HTTPException(status_code=400, detail="모의 계획은 확인 코드가 필요 없습니다")
        try:
            cid = await sw.request_challenge(s, action=body.action, send=_send_code, plan_id=p.id,
                                             revision=p.revision, content_hash=p.content_hash)
        except sw.ConfirmError as exc:
            raise await _confirm_fail(s, exc)
        return {"challenge_id": cid, "revision": p.revision, "content_hash": p.content_hash[:12],
                "expires_in_sec": int(sw.CODE_TTL.total_seconds()), "values": approval_values(p)}


class ConfirmBody(BaseModel):
    challenge_id: Optional[int] = None
    code: Optional[str] = Field(None, max_length=12)
    approver: str = "대표"


async def _verify(s, plan: Plan, action: str, body: ConfirmBody) -> None:
    if plan.mode == "paper":
        return
    if body.challenge_id is None or not body.code:
        raise HTTPException(status_code=400, detail={"reason": "code_required", "message": "텔레그램 확인 코드가 필요합니다"})

    async def _fail(attempts: int) -> None:
        await _alert("critical", "확인 코드 실패", f"계획 번호 {plan.id} · 동작 {sw.ACTION_LABEL.get(action, action)} · 틀린 코드 입력")

    try:
        await sw.verify_challenge(s, challenge_id=body.challenge_id, code=body.code, action=action, plan_id=plan.id,
                                  revision=plan.revision, content_hash=plan.content_hash, on_fail=_fail)
    except sw.ConfirmError as exc:
        raise await _confirm_fail(s, exc)


@router.post("/{plan_id:int}/approve")
async def approve_plan(plan_id: int, body: ConfirmBody, src: str = Depends(require_plan_cookie)) -> dict:
    eng = _engine()
    eng.kill_state = _kill_state
    try:
        async with get_session() as s:
            p = await _get_plan(s, plan_id)
            is_adopt = p.source == "adopt"
            if p.mode != "paper" and body.approver != "대표":
                raise HTTPException(status_code=400, detail="실전 · 시험 계획은 대표만 승인합니다")
            await _verify(s, p, "adopt" if is_adopt else "approve", body)
            await eng.approve(s, p, by=body.approver)
            if is_adopt:
                await eng.adopt_approve(s, p)
            return {"plan": _plan_json(p)}
    except state.TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{plan_id:int}/resume")
async def resume_plan(plan_id: int, body: ConfirmBody, src: str = Depends(require_plan_cookie)) -> dict:
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        if p.state != state.HALTED:
            raise HTTPException(status_code=409, detail="정지 상태가 아닙니다")
        await _verify(s, p, "resume", body)
        req = await _queue(s, p, "resume", src)
        return {"queued": req.id}


# ─── 스위치 (쿠키만 + Origin) ─────────────────────────────────────

class SwitchBody(BaseModel):
    on: bool
    reason: str = Field("", max_length=200)
    challenge_id: Optional[int] = None
    code: Optional[str] = Field(None, max_length=12)


@router.post("/switches/live/challenge")
async def live_challenge(src: str = Depends(require_plan_cookie)) -> dict:
    async with get_session() as s:
        try:
            cid = await sw.request_challenge(s, action="live_on", send=_send_code)
        except sw.ConfirmError as exc:
            raise await _confirm_fail(s, exc)
        return {"challenge_id": cid, "expires_in_sec": int(sw.CODE_TTL.total_seconds())}


async def _switch_alert(name: str, old: bool, new: bool, reason: str, actor: str) -> None:
    label = "실거래 주문" if name == "live" else "모의 시험"
    await _alert("critical" if (name == "live" and new) else "warning", f"계획 스위치 변경 · {label}",
                 f"{label}: {'켜짐' if old else '꺼짐'} → {'켜짐' if new else '꺼짐'}\n누가: {actor}\n까닭: {reason or '—'}")


@router.post("/switches/live")
async def set_live(body: SwitchBody, request: Request, src: str = Depends(require_plan_cookie)) -> dict:
    async with get_session() as s:
        if body.on:
            if not body.reason.strip():
                raise HTTPException(status_code=400, detail="까닭을 적어 주십시오")
            if body.challenge_id is None or not body.code:
                raise HTTPException(status_code=400, detail={"reason": "code_required", "message": "텔레그램 확인 코드가 필요합니다"})

            async def _fail(attempts: int) -> None:
                await _alert("critical", "확인 코드 실패", "동작 실거래 켜기 · 틀린 코드 입력")

            try:
                await sw.verify_challenge(s, challenge_id=body.challenge_id, code=body.code, action="live_on",
                                          plan_id=None, on_fail=_fail)
            except sw.ConfirmError as exc:
                raise await _confirm_fail(s, exc)
        old = await sw.set_switch(s, "live", body.on, actor="대표(쿠키)", reason=body.reason)
    await _switch_alert("live", old, body.on, body.reason, "대표(쿠키)")
    return {"live": body.on, "previous": old}


@router.post("/switches/paper")
async def set_paper(body: SwitchBody, src: str = Depends(require_plan_cookie)) -> dict:
    if body.on and not body.reason.strip():
        raise HTTPException(status_code=400, detail="까닭을 적어 주십시오")
    async with get_session() as s:
        old = await sw.set_switch(s, "paper", body.on, actor="대표(쿠키)", reason=body.reason)
    await _switch_alert("paper", old, body.on, body.reason, "대표(쿠키)")
    return {"paper": body.on, "previous": old}
