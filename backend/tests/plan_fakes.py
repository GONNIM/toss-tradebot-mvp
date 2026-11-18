"""계획 실행기 시험 도구 · 가짜 토스 브로커 · 가상 종목(TESTA · TESTB)과 가상 가격만 쓴다 (실제 호출 0)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import delete

from backend.execution.exceptions import ExecutionError, OrderRejected
from backend.execution.plan import state
from backend.execution.plan.brokers import DirectionGate, RawBroker
from backend.execution.plan.engine import PlanEngine
from backend.execution.plan.models import (
    Plan, PlanConfirmChallenge, PlanEvent, PlanExecutorHeartbeat, PlanFill, PlanLeg, PlanLegPending,
    PlanPaperOrder, PlanPaperPosition, PlanRequest, PlanSellReservation, PlanSwitchAudit,
)

PLAN_TABLES = (Plan, PlanLeg, PlanFill, PlanSellReservation, PlanEvent, PlanRequest, PlanLegPending,
               PlanPaperPosition, PlanPaperOrder, PlanSwitchAudit, PlanConfirmChallenge, PlanExecutorHeartbeat)

D = Decimal


@pytest.fixture
async def plan_db(monkeypatch, tmp_path):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("PLAN_SWITCH_PATH", str(tmp_path / "plan_switches.json"))
    await init_db()
    async with get_session() as s:
        for m in PLAN_TABLES:
            await s.execute(delete(m))
    yield
    async with get_session() as s:
        for m in PLAN_TABLES:
            await s.execute(delete(m))


class FakeRaw(RawBroker):
    """가짜 토스. 가격 · 보유 · 실패를 시험이 정한다. 부른 일은 calls 에 남는다."""

    mode = "fake"

    def __init__(self, price="10"):
        self.price = D(price)
        self.price_queue: list = []          # 값이 있으면 읽을 때마다 하나씩 꺼낸다 (두 값 확인용)
        self.acct = 0
        self.conds: dict[str, dict] = {}
        self.limits: dict[str, dict] = {}
        self.n = 0
        self.calls: list[tuple] = []
        self.fail_modify = 0
        self.reject_sell: Optional[str] = None   # 지정가 매도를 이 코드로 거절
        self.reject_cond_code: Optional[str] = None
        self.reject_cond_sides: tuple = ("BUY", "SELL")
        self.cancel_fail = False
        self.create_no_id = False        # 조건주문을 만들고도 응답에 번호가 없는 것처럼 오류 (불확실한 실패)
        self.create_timeout = False      # 조건주문을 만들기 전에 시간 초과 오류
        self.limit_uncertain = False     # 지정가 주문을 만들고도 응답이 오류 (불확실한 실패)

    def _id(self, p):
        self.n += 1
        return f"{p}{self.n}"

    async def last_price_rest(self, s, symbol):
        if self.price_queue:
            return D(self.price_queue.pop(0))
        return self.price

    async def account_qty(self, s, plan_id, symbol):
        return self.acct

    async def cond_create(self, s, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        self.calls.append(("cond_create", side, qty, D(watch), D(order), client_id))
        if self.reject_cond_code and side in self.reject_cond_sides:
            raise OrderRejected(self.reject_cond_code, "거절")
        if self.create_timeout:
            raise ExecutionError("시간 초과")
        cid = self._id("C")
        self.conds[cid] = dict(id=cid, status="WATCHING", symbol=symbol, side=side, qty=qty, watch=D(watch),
                               order=D(order), client_id=client_id, order_id=None, filled=0, remaining=qty, avg=None,
                               expire=expire)
        if self.create_no_id:
            raise ExecutionError("토스 응답에 번호가 없습니다")
        return cid

    async def cond_modify(self, s, cond_id, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        self.calls.append(("cond_modify", cond_id, qty, D(watch), D(order), client_id))
        if self.fail_modify > 0:
            self.fail_modify -= 1
            raise ExecutionError("수정 실패")
        self.conds[cond_id]["status"] = "CANCELED"
        cid = self._id("C")
        self.conds[cid] = dict(id=cid, status="WATCHING", symbol=symbol, side=side, qty=qty, watch=D(watch),
                               order=D(order), client_id=client_id, order_id=None, filled=0, remaining=qty, avg=None,
                               expire=expire)
        return cid

    async def cond_cancel(self, s, cond_id):
        self.calls.append(("cond_cancel", cond_id))
        if self.cancel_fail:
            raise ExecutionError("취소 실패")
        if cond_id in self.conds:
            self.conds[cond_id]["status"] = "CANCELED"

    async def cond_get(self, s, cond_id):
        c = self.conds.get(cond_id)
        return dict(c) if c else None

    async def cond_open_list(self, s, symbol=None):
        return [dict(c) for c in self.conds.values()
                if c["status"] == "WATCHING" and (symbol is None or c["symbol"] == symbol)]

    async def limit_create(self, s, *, plan_id, symbol, side, qty, price, client_id):
        self.calls.append(("limit_create", side, qty, D(price), client_id))
        if side == "SELL" and self.reject_sell:
            raise OrderRejected(self.reject_sell, "거절")
        oid = self._id("L")
        self.limits[oid] = dict(status="OPEN", symbol=symbol, side=side, qty=qty, price=D(price), filled=0,
                                remaining=qty, avg=None, client_id=client_id)
        if self.limit_uncertain:
            raise ExecutionError("시간 초과")
        return oid

    async def limit_cancel(self, s, order_id):
        self.calls.append(("limit_cancel", order_id))
        if self.cancel_fail:
            raise ExecutionError("취소 실패")
        if order_id in self.limits and self.limits[order_id]["status"] == "OPEN":
            self.limits[order_id]["status"] = "CANCELED"

    async def limit_get(self, s, order_id):
        o = self.limits.get(order_id)
        return dict(o) if o else None

    async def limit_open_list(self, s, symbol=None):
        return [{"id": k, "client_id": o.get("client_id"), "symbol": o["symbol"], "side": o["side"], "qty": o["qty"],
                 "price": o["price"]} for k, o in self.limits.items()
                if o["status"] == "OPEN" and (symbol is None or o["symbol"] == symbol)]

    # ── 시험 조작 ──
    def trigger(self, cond_id, *, fill=True):
        c = self.conds[cond_id]
        c["status"] = "FILLED" if fill else "TRIGGERED"
        if fill:
            c["filled"], c["remaining"], c["avg"] = c["qty"], 0, c["order"]
        else:
            c["order_id"] = "T" + cond_id

    def fill_limit(self, oid):
        o = self.limits[oid]
        o["status"], o["filled"], o["remaining"], o["avg"] = "FILLED", o["qty"], 0, o["price"]

    def count(self, kind):
        return len([c for c in self.calls if c[0] == kind])


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


async def _noop(*a, **k):
    return None


def make_engine(raw: RawBroker, *, clock=None, alerts=None, limit_factor=D("0.98"), regular=None, switches=None,
                kill=(False, True)):
    """regular: (시작, 끝) 또는 None. 값이 없으면 정규장 밖(off)이다."""
    alerts = alerts if alerts is not None else []

    async def notify(level, title, body, category):
        alerts.append((level, title, body, category))

    clock = clock or Clock(datetime(2026, 11, 20, 15, 0))
    eng = PlanEngine(
        DirectionGate(raw), notify=notify, clock=clock,
        limit_factor=(lambda now: limit_factor),
        regular_window=(lambda now: regular),
        switches=(switches or (lambda: {"live": True, "paper": True})),
        kill_state=(lambda: kill),
    )
    eng._alerts = alerts
    return eng


async def seed_holding(s, eng, *, symbol="TESTA", qty=60, avg=10.0, mode="live", extra=None, state_=state.HOLDING):
    """HOLDING 계획 한 건: 매수 체결 qty 주 · 평단 avg."""
    params = {"buy_watch": avg, "buy_order": avg, "qty": qty, "ladder_pcts": [0.03, 0.05, 0.07]}
    params.update(extra or {})
    plan = await eng.create_draft(s, symbol=symbol, mode=mode, params=params)
    plan.state = state_
    plan.avg_price = avg
    s.add(PlanFill(plan_id=plan.id, side="BUY", qty=qty, price=avg, order_ref=f"seed-{plan.id}", fill_seq=qty))
    await s.flush()
    return plan
