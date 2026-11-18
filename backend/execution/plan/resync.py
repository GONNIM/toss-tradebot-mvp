"""다시 맞추기 · 계획서 7-2 · 9절 · 6-1 만료일.

기동 · 재연결 · 5분마다 조건주문 · 보유 · 주문을 읽어 장부와 대조한다.
계획이 만든 번호만 계획 다리다. 계획 밖 매도와 계획 다리 합이 계좌 보유를 넘으면 ⑨ 긴급.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from . import sizing, state
from .engine import EXPIRE_EXTEND_BELOW_DAYS, PlanEngine, _num, set_runtime
from .models import Plan, PlanLeg, PlanLegPending
from .pricing import D

_ACTIVE_STATES = (state.HOLDING, state.TP1_WAIT, state.TRAILING, state.HALTED)


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


async def _resolve_pending(s, eng: PlanEngine, plan: Plan, open_conds: list[dict]) -> dict:
    """수정 중 기록(7-2): 1순위 clientOrderId · 2순위 값 일치(이미 다른 다리에 이어진 번호는 뺌) · 후보 1개면 잇는다."""
    out = {"linked": 0, "retry": 0, "lost": 0, "halted": False}
    pendings = list(await s.scalars(select(PlanLegPending).where(PlanLegPending.plan_id == plan.id)))
    if not pendings:
        return out
    linked_ids = {l.toss_id for l in await s.scalars(select(PlanLeg).where(
        PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING")) if l.toss_id}
    open_ids = {o["id"] for o in open_conds if o}
    for pend in pendings:
        leg = await s.get(PlanLeg, pend.leg_id)
        if leg is None:
            await s.delete(pend)
            continue
        taken = linked_ids - {pend.old_toss_id}
        cands = [o for o in open_conds if o and o["id"] not in taken and o["id"] != pend.old_toss_id
                 and o.get("client_id") == pend.client_order_id]
        if not cands:
            cands = [o for o in open_conds if o and o["id"] not in taken and o["id"] != pend.old_toss_id
                     and o.get("side") == "SELL" and o.get("qty") == pend.qty
                     and _same(o.get("watch"), pend.new_watch) and _same(o.get("order"), pend.new_order)]
        if len(cands) > 1:
            await eng._halt(s, plan, "수정 중 기록에 맞는 조건주문이 여럿 (넘침)")
            out["halted"] = True
            return out
        if len(cands) == 1:
            leg.toss_id, leg.qty = cands[0]["id"], pend.qty
            leg.watch_price, leg.order_price, leg.client_order_id = pend.new_watch, pend.new_order, pend.client_order_id
            linked_ids.add(leg.toss_id)
            out["linked"] += 1
        elif pend.old_toss_id in open_ids:
            leg.tag = ""        # 옛 값으로 두고 시간대 교대가 수정을 다시 시도한다 (틀린 시간대 값이 남지 않게)
            out["retry"] += 1
        else:
            leg.status = "CANCELED"   # 옛 · 새 모두 없음 → 모자람으로 보고 보호 다리를 다시 건다
            out["lost"] += 1
        await s.delete(pend)
    await s.flush()
    return out


async def resync_plan(s, eng: PlanEngine, plan: Plan, now: Optional[datetime] = None) -> dict:
    now = now or eng.clock()
    eng.gate.end_tick()                                  # 걸음 캐시를 쓰지 않는다 (계좌 보유를 새로 읽는다)
    rep: dict = {"plan_id": plan.id, "ok": True}
    if plan.state not in _ACTIVE_STATES:
        return rep
    open_conds = await eng.gate.cond_open_list(s, plan.symbol)
    # 수정 중 기록을 먼저 풀어야 한다 (옛 번호가 닫혀 있다고 다리를 먼저 지우면 새 주문과 짝을 못 잇는다)
    rep["pending"] = await _resolve_pending(s, eng, plan, open_conds)
    if rep["pending"]["halted"]:
        rep["ok"] = False
        return rep
    await eng.sync_orders(s, plan)
    # 만료일: 남은 기간이 10일 아래면 같은 값으로 수정해 연장 · EXPIRED 는 모자람으로 다룸
    limit = (now + timedelta(days=EXPIRE_EXTEND_BELOW_DAYS)).strftime("%Y-%m-%d")
    for leg in await sizing.live_sl_legs(s, plan.id):
        if leg.expire_date and leg.expire_date < limit:
            await eng._modify_leg(s, plan, leg)
            rep["extended"] = rep.get("extended", 0) + 1
    # 계획 밖 매도 + 계획 다리 합이 계좌 보유를 넘는가 (모의는 실제 계좌를 보지 않는다)
    if plan.mode != "paper":
        own = {l.toss_id for l in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)) if l.toss_id}
        foreign = sum(o["qty"] for o in open_conds if o and o["id"] not in own and o.get("side") == "SELL")
        legs = await sizing.live_sl_legs(s, plan.id)
        acct = await eng.gate.account_qty(s, plan.id, plan.symbol)
        mine = sum(l.qty for l in legs) + await sizing.accepted_sell(s, plan.id)
        if foreign + mine > acct:
            rep["ok"] = False
            await eng._alert(plan, "critical", "매도 합이 계좌 보유를 넘음",
                             f"계획 밖 매도 {foreign}주 + 계획 다리 {mine}주가 계좌 보유 {acct}주를 넘습니다.")
    rep["ladder"] = await eng.ensure_ladder(s, plan)
    await _save_actual(s, eng, plan, open_conds, now)
    return rep


async def _save_actual(s, eng: PlanEngine, plan: Plan, open_conds: list[dict], now: datetime) -> None:
    """화면용: 다시 맞추기가 마지막으로 본 토스(또는 모의)의 실제 다리 · 계좌 보유 (계획 상세 「실제 걸린 다리」)."""
    legs = list(await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)))
    by_id = {l.toss_id: l for l in legs if l.toss_id}
    actual = []
    for o in open_conds:
        if o and o["id"] in by_id:
            l = by_id[o["id"]]
            actual.append({"toss_id": o["id"], "role": l.role, "qty": o.get("qty"), "watch": _num(o.get("watch")),
                           "order": _num(o.get("order"))})
    for l in legs:                                         # 일반 지정가(매수)는 조건주문 목록에 없다
        if l.kind == "limit" and l.status == "WATCHING" and l.toss_id:
            g = await eng.gate.limit_get(s, l.toss_id)
            if g and g.get("status") == "OPEN":
                actual.append({"toss_id": l.toss_id, "role": l.role, "qty": g.get("remaining"), "watch": l.watch_price,
                               "order": l.order_price})
    acct = await eng.gate.account_qty(s, plan.id, plan.symbol)
    set_runtime(plan, actual_legs=actual, actual_at=now.isoformat(), account_qty=int(acct), account_qty_at=now.isoformat())


async def resync_all(s, eng: PlanEngine, now: Optional[datetime] = None) -> list[dict]:
    plans = list(await s.scalars(select(Plan).where(Plan.state.in_(_ACTIVE_STATES))))
    return [await resync_plan(s, eng, p, now) for p in plans]
