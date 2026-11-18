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
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.api.auth import require_plan_cookie, require_plan_write, require_sniper_token
from backend.execution.exceptions import ExecutionError
from backend.execution.plan import heartbeat, sizing, state
from backend.execution.plan import switches as sw
from backend.execution.plan.brokers import DirectionGate, RawBroker
from backend.execution.plan.engine import PlanEngine, approval_values, derive_qty, params_of, parse_dt, runtime_of
from backend.execution.plan.models import (
    Plan, PlanEvent, PlanExecutorHeartbeat, PlanLeg, PlanRequest, PlanSwitchAudit, PlanSellReservation,
)
from backend.services.models import UserJudgment
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


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _qty_of(p: Plan):
    pr = params_of(p)
    v = pr.get("qty")
    if v is None:
        v = (pr.get("adopt") or {}).get("qty")
    return v


_DATE_KEYS = ("announce_at", "entry_close_at", "entry_window_end")


def _check_dates(values: dict) -> None:
    """날짜 칸은 `YYYY-MM-DDTHH:mm:00+09:00`(시간대 포함) · 시간대 없는 값 · Z 모두 받는다. 읽지 못하면 400. null · 빈 값은 지움."""
    for k in _DATE_KEYS:
        v = values.get(k)
        if v in (None, ""):
            continue
        try:
            parse_dt(v)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail={"reason": "bad_date", "message": f"{k} 날짜 형식이 올바르지 않습니다 (예: 2026-12-10T22:00:00+09:00)"})


def _plan_json(p: Plan) -> dict:
    return {
        "id": p.id, "mode": p.mode, "source": p.source, "symbol": p.symbol, "state": p.state,
        "revision": p.revision, "halted_reason": p.halted_reason, "approved_by": p.approved_by,
        "avg_price": p.avg_price, "peak_price": p.peak_price, "timestop_stage": p.timestop_stage,
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "qty": _qty_of(p),
        "params": params_of(p), "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def _get_plan(s, plan_id: int) -> Plan:
    p = await s.get(Plan, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="계획을 찾을 수 없습니다")
    return p


# ─── 조회 (관리자 · 쿠키 또는 헤더) ───────────────────────────────

async def _toss_state(s) -> dict:
    """화면 띠용 「토스 API 연결 · 마지막 성공 시각」 (실행기가 남긴 값 · 화면 서버는 토스를 부르지 않는다)."""
    row = await s.get(PlanExecutorHeartbeat, 1)
    return {"status": row.toss_status if row else "none",
            "last_ok_at": row.toss_ok_at.isoformat() if row and row.toss_ok_at else None}


async def _tp1_mode(s, p: Plan) -> Optional[str]:
    """register(조건주문 등록) | watch(감시 모드) | None(아직 정해지지 않음 · 보유 전)."""
    if await sizing.live_tp1_leg(s, p.id) is not None:
        return "register"
    if await s.scalar(select(PlanSellReservation.id).where(
            PlanSellReservation.plan_id == p.id, PlanSellReservation.kind == "tp1_watch",
            PlanSellReservation.active.is_(True)).limit(1)) is not None:
        return "watch"
    return runtime_of(p).get("tp1_mode")


@router.get("")
async def list_plans(_: str = Depends(require_sniper_token)) -> dict:
    """plans[] 각 줄에 live_cond_count(걸린 조건주문 수) · tp1_mode · price(마지막 현재가) 를 더했고, toss 칸을 더했다."""
    async with get_session() as s:
        rows = list(await s.scalars(select(Plan).order_by(Plan.id.desc()).limit(200)))
        out = []
        for p in rows:
            n = await s.scalar(select(func.count()).select_from(PlanLeg).where(
                PlanLeg.plan_id == p.id, PlanLeg.status == "WATCHING", PlanLeg.kind == "cond"))
            rt = runtime_of(p)
            out.append({**_plan_json(p), "live_cond_count": int(n or 0), "tp1_mode": await _tp1_mode(s, p),
                        "price": rt.get("price"), "price_at": rt.get("price_at")})
        return {"plans": out, "toss": await _toss_state(s)}


def _paper_test_enabled() -> bool:
    """PLAN_PAPER_TEST_ENABLED(v4 8절) 가 켜졌거나 모의 스위치가 켜져 있으면 「모의 시험 계획 만들기」 를 보인다."""
    from backend.services import config

    flag = (config.get("PLAN_PAPER_TEST_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
    return flag or bool(sw.read_switches()["paper"])


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
            "paper_test_enabled": _paper_test_enabled(),
            "toss": await _toss_state(s),
        }


@router.get("/{plan_id:int}")
async def plan_detail(plan_id: int, _: str = Depends(require_sniper_token)) -> dict:
    now = datetime.utcnow()
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        legs = list(await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == p.id).order_by(PlanLeg.id)))
        events = list(await s.scalars(select(PlanEvent).where(PlanEvent.plan_id == p.id).order_by(PlanEvent.id.desc()).limit(100)))
        base = await sizing.plan_qty(s, p)
        acc = await sizing.accepted_sell(s, p.id)
        live = await sizing.live_sl_legs(s, p.id)
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in live])
        rt = runtime_of(p)
        pr = params_of(p)
        price, avg = rt.get("price"), p.avg_price
        pnl = None
        if price is not None and avg:
            pnl = {"usd": round((price - avg) * base, 4), "pct": round((price - avg) / avg * 100, 2), "estimate": True}
        tp1 = pr.get("tp1_watch")
        tp1_gap = None
        if price and tp1 and p.state in (state.HOLDING, state.TP1_WAIT):
            tp1_gap = round((float(tp1) - price) / price * 100, 2)
        trailing = None
        if p.state == state.TRAILING:
            trailing = {"peak": p.peak_price, "stop": min([l.watch_price for l in live if l.watch_price] or [None], default=None)}
        acct = rt.get("account_qty")
        adopt = None
        if p.state == state.ADOPT_PENDING:
            checked = rt.get("adopt_checked_at")
            left = None
            if checked:
                left = max(0, 10 - int((now - datetime.fromisoformat(checked)).total_seconds()))
            adopt = {"foreign_conds": rt.get("adopt_foreign") or [], "checked_at": checked, "seconds_left": left,
                     "max_gap_sec": 10, "waiting_minutes": int((now - p.approved_at).total_seconds() // 60) if p.approved_at else None}
        return {
            "plan": _plan_json(p),
            "approval_values": approval_values(p),
            "content_hash": p.content_hash[:12],
            "legs": [{"id": l.id, "role": l.role, "seq": l.seq, "kind": l.kind, "qty": l.qty, "watch": l.watch_price,
                      "order": l.order_price, "status": l.status, "tag": l.tag} for l in legs],
            "events": [{"ts": e.ts.isoformat(), "kind": e.kind, "detail": e.detail} for e in events],
            "invariant": {"status": rep.status, "plan_qty": base, "accepted_sell": acc, "sl_sum": rep.sl_sum,
                          "target": rep.target},
            # 실행기가 남긴 마지막 값 (없으면 null · 화면은 「—」)
            "actual_legs": rt.get("actual_legs"), "actual_at": rt.get("actual_at"),
            "live": {
                "price": price, "price_at": rt.get("price_at"), "pnl": pnl, "next_swap_at": rt.get("next_swap_at"),
                "tp1_gap_pct": tp1_gap, "trailing": trailing, "tp1_mode": await _tp1_mode(s, p),
                "plan_qty": base, "account_qty": acct, "account_qty_at": rt.get("account_qty_at"),
                "outside_qty": max(0, acct - base) if acct is not None else None,
            },
            "adopt": adopt,
        }


# ─── 새 계획 · 초안 수정 · 정지 (쿠키 · 헤더) ──────────────────────────

class PlanCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    mode: str = Field(..., pattern="^(paper|live|test)$")
    source: str = Field("manual", pattern="^(manual|adopt)$")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def create_plan(body: PlanCreate, src: str = Depends(require_plan_write)) -> dict:
    _check_dates(body.params)
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
    _check_dates(body.values)
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


@router.post("/{plan_id:int}/resync")
async def resync_request(plan_id: int, src: str = Depends(require_plan_write)) -> dict:
    """「토스와 다시 맞추기」 · 위험을 줄이는 점검이라 쿠키 · 헤더 모두 허용(쿠키는 Origin 검사) · 실행기가 처리한다."""
    async with get_session() as s:
        p = await _get_plan(s, plan_id)
        if p.state in state.TERMINAL or p.state == state.DRAFT:
            raise HTTPException(status_code=409, detail="이 단계에서는 다시 맞출 것이 없습니다")
        req = await _queue(s, p, "resync", src)
        return {"queued": req.id}


# ─── 새 계획 검증 (읽기 전용 · 아무것도 저장하지 않는다) ───────────────────────

@router.post("/validate")
async def validate_plan(body: PlanCreate, _: str = Depends(require_sniper_token)) -> dict:
    """상한 · 매수 가능 금액 · 가격 단위 · sanity · 같은 종목 열린 계획 · 앱에서 건 조건주문을 점검한다.
    토스가 필요한 칸(매수 가능 금액 · 앱 조건주문)은 실행기가 마지막으로 남긴 값이고, 없으면 status=unknown(「확인 못 함」)."""
    from backend.execution.plan import pricing as pr
    from backend.execution.plan import sanity

    checks: list[dict] = []

    def add(key, label, status, message):
        checks.append({"key": key, "label": label, "status": status, "message": message})

    prm = body.params or {}
    sym = body.symbol.upper()
    try:
        _check_dates(prm)
        add("dates", "날짜 형식", "ok", "")
    except HTTPException as exc:
        add("dates", "날짜 형식", "fail", exc.detail["message"])
    adopt = body.source == "adopt"
    given_qty = int(_f(prm.get("qty") or (prm.get("adopt") or {}).get("qty")) or 0)
    server_qty = derive_qty(prm)                      # 수량은 서버 한 곳에서 정한다 (계획서 6절)
    qty = server_qty if server_qty is not None else given_qty
    bw, bo = _f(prm.get("buy_watch")), _f(prm.get("buy_order"))
    tw, to = _f(prm.get("tp1_watch")), _f(prm.get("tp1_order"))
    # 가격 단위
    bad = [k for k, v in (("buy_watch", bw), ("buy_order", bo), ("tp1_watch", tw), ("tp1_order", to))
           if v is not None and pr.floor_tick(v) != pr.D(v)]
    add("tick", "가격 단위", "fail" if bad else "ok",
        ("가격 단위(1달러 미만 0.0001 · 이상 0.01)에 맞지 않는 칸: " + ", ".join(bad)) if bad else "")
    if server_qty is not None:
        why = "" if qty > 0 else "예산이 매수가보다 작아 수량이 0 입니다"
        extra = f" (보낸 수량 {given_qty} 는 쓰지 않습니다)" if given_qty and given_qty != qty else ""
        add("qty", "수량", "ok" if qty > 0 else "fail",
            why or f"예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림 = {qty}주{extra}")
    async with get_session() as s:
        open_exists = await sizing.open_plan_exists(s, sym)
        add("open_plan", "같은 종목 열린 계획", "fail" if open_exists else "ok", "같은 종목에 열린 계획이 이미 있습니다" if open_exists else "")
        # 금액 상한
        order_usd = (bo or 0) * qty
        if adopt:
            add("caps", "금액 상한", "ok", "보유 인수는 새 매수가 없습니다")
        else:
            open_total = await _open_total(s)
            why = pr.check_caps(mode=body.mode, order_usd=order_usd, open_total_usd=open_total)
            add("caps", "금액 상한", "fail" if why else "ok", why or "")
        # 매수 가능 금액 (실행기가 남긴 마지막 값)
        row = await s.get(PlanExecutorHeartbeat, 1)
        if adopt or body.mode == "paper":
            add("buying_power", "매수 가능 금액", "ok", "이 계획은 실제 매수가 없습니다")
        elif row is None or row.buying_power_usd is None:
            add("buying_power", "매수 가능 금액", "unknown", "확인 못 함 · 실행기가 아직 값을 남기지 않았습니다")
        else:
            enough = row.buying_power_usd >= order_usd
            add("buying_power", "매수 가능 금액", "ok" if enough else "fail",
                f"마지막으로 본 값 {row.buying_power_usd:,.2f}달러 ({row.buying_power_at.isoformat()})" + ("" if enough else " · 주문 금액보다 작습니다"))
        # 앱에서 건 같은 종목 조건주문 (실행기가 남긴 마지막 값)
        if row is None or not row.app_conds_json:
            add("app_conds", "앱에서 건 조건주문", "unknown", "확인 못 함 · 실행기가 아직 값을 남기지 않았습니다")
        else:
            n = int(json.loads(row.app_conds_json).get(sym, 0))
            add("app_conds", "앱에서 건 조건주문", "warn" if n else "ok",
                (f"앱 조건주문 {n}건이 있습니다 · 보유 인수는 지운 뒤 10초 안에 실행기 손절이 걸립니다" if n else "없음")
                + f" (마지막 확인 {row.app_conds_at.isoformat()})")
        # sanity (최근 현재가가 있을 때만 · 없으면 확인 못 함)
        last_price = None
        for pl in await s.scalars(select(Plan).where(Plan.symbol == sym).order_by(Plan.id.desc()).limit(5)):
            last_price = runtime_of(pl).get("price")
            if last_price:
                break
    msgs = []
    if bw is not None and last_price:
        w = sanity.check_band(bw, last_price, "매수 감시")
        if w:
            msgs.append(w)
    if tw is not None and (bo or bw):
        w = sanity.check_tp1(tw, bo or bw)
        if w:
            msgs.append(w)
    if msgs:
        add("sanity", "값 점검(sanity)", "fail", " / ".join(msgs))
    elif bw is not None and not last_price:
        add("sanity", "값 점검(sanity)", "unknown", "확인 못 함 · 최근 현재가가 없어 직전가 ±40% 는 보지 못했습니다 (TP1 은 점검함)")
    else:
        add("sanity", "값 점검(sanity)", "ok", "")
    return {"ok": not any(c["status"] == "fail" for c in checks), "checks": checks,
            "values": {"order_usd": round(order_usd, 4), "qty": qty, "qty_source": "server" if server_qty is not None else "given",
                       "qty_given": given_qty}}


async def _open_total(s) -> float:
    total = 0.0
    for r in await s.scalars(select(Plan).where(Plan.mode != "paper", Plan.state.in_(sizing.OPEN_STATES))):
        pr_ = params_of(r)
        total += (_f(pr_.get("buy_order") or r.avg_price) or 0) * int(_f(pr_.get("qty") or r.plan_qty_hint) or 0)
    return total


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
    # 승인과 한 트랜잭션으로 저장하는 판단 기록 (v4 8절 · 판정 3줄: 근거 · 무효 가격 · 목표 가격)
    ticker: Optional[str] = Field(None, max_length=16)         # 직접 입력한 종목 이름 · 있으면 계획 종목과 같아야 함
    thesis: Optional[str] = Field(None, max_length=4000)
    invalidation_price: Optional[float] = None
    target_price: Optional[float] = None


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
            if body.ticker is not None and body.ticker.strip().upper() != p.symbol:
                raise HTTPException(status_code=400, detail={"reason": "ticker_mismatch", "message": "입력한 종목 이름이 계획 종목과 다릅니다"})
            wants_judgment = p.mode != "paper" or any(v is not None for v in (body.thesis, body.invalidation_price, body.target_price))
            if wants_judgment and (not (body.thesis or "").strip() or not (body.invalidation_price and body.invalidation_price > 0)):
                raise HTTPException(status_code=400, detail={"reason": "judgment_required", "message": "판단 기록(근거 · 무효 가격)이 필요합니다"})
            await _verify(s, p, "adopt" if is_adopt else "approve", body)
            await eng.approve(s, p, by=body.approver)
            if is_adopt:
                await eng.adopt_approve(s, p)
            if wants_judgment:                      # 같은 세션 · 위에서 하나라도 실패하면 둘 다 남지 않는다
                pr = params_of(p)
                s.add(UserJudgment(
                    ticker=p.symbol, page_source="plans", hypothesis_id="plan-executor-1116-01",
                    thesis_md=body.thesis.strip(), invalidation_price=body.invalidation_price,
                    target_price=body.target_price, horizon_days=7, mood="neutral", market_regime="unknown",
                    entry_price=_f(pr.get("buy_order") or p.avg_price), strategy="event", qty=_f(_qty_of(p)),
                ))
                await s.flush()
            return {"plan": _plan_json(p), "judgment_saved": bool(wants_judgment)}
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
