"""주문 장부 · 결과 모르는 주문 대조 · 계획서 5절 10항 · 7-2 (1116-01 · Fable 재설계 · 사용자 11/18 승인).

한 번 보낼 때마다 장부 한 줄(PlanOrderBook)을 먼저 남긴다. 결과를 모르는 주문(번호 없는 응답 · 시간 초과)은
이 모듈의 `reconcile` 한 곳이 판정한다. 규칙:

1. 낸 뒤 `PLAN_ORDER_SETTLE_SEC`(기본 90초) 안에는 「없음」으로 단정하지 않는다.
2. 목록에서 clientOrderId 로 찾을 수 있는지는 설정(`PLAN_ORDER_LIST_SEARCHABLE` · 기본 꺼짐 = 못 찾음).
   꺼져 있으면 모르는 주문은 모두 「그 수량 묶음 + 사람 확인」이다. U6(소액 시험 첫 순서) 결과가 나오면 설정만 바꾼다.
3. 목록 쪽 나눔을 아는지는 설정(`PLAN_ORDER_LIST_PAGING_KNOWN` · 기본 꺼짐). 모르는 동안에는 목록에 없다는 것을 「안 만들어짐」 근거로 쓰지 않는다.
4. 같은 clientOrderId 가 둘이면 자동 연결하지 않고 사람에게 간다. 수량 · 가격이 같다는 값 일치(2순위)로는 자동 연결하지 않고 후보로만 보여 준다.
5. 계좌 보유 변화는 체결의 근거가 아니다(상한 검사 · 경보에만 쓴다). 체결 줄(PlanFill)은 토스 주문 상태 또는 사람의 확정으로만 만든다.
6. 모름인 동안 그 수량은 묶는다(손절은 그 수량을 뺀 나머지 보호를 계속 건다). ⑨ 긴급 알림을 되풀이해 보낸다.
7. 부모 조건주문 – 자식 주문 관계(발동된 조건주문이 만든 주문)를 장부에 적는다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from .models import PlanFill, PlanLeg, PlanOrderBook, PlanSellReservation, utcnow

logger = logging.getLogger(__name__)

SENT_UNKNOWN, OPEN, CLOSED, NOT_CREATED, NEEDS_HUMAN = "sent_unknown", "open", "closed", "not_created", "needs_human"
UNRESOLVED = (SENT_UNKNOWN, NEEDS_HUMAN)
REPEAT_ALERT_SEC = 600


def _cfg(name: str) -> str:
    from backend.services import config

    return (config.get(name) or "").strip()


def settle_sec() -> int:
    try:
        return max(0, int(_cfg("PLAN_ORDER_SETTLE_SEC") or 90))
    except ValueError:
        return 90


def list_searchable() -> bool:
    """토스 목록에서 clientOrderId 로 찾을 수 있는가 · 기본 「못 찾음」 (U6 확인 전)."""
    return _cfg("PLAN_ORDER_LIST_SEARCHABLE").lower() in ("1", "true", "yes", "on")


def list_paging_known() -> bool:
    """목록 쪽 나눔 · 보관 기간을 알고 모든 쪽을 읽는가 · 기본 「모름」."""
    return _cfg("PLAN_ORDER_LIST_PAGING_KNOWN").lower() in ("1", "true", "yes", "on")


# ─── 기록 ──────────────────────────────────────────────────────

async def send(s, plan, *, cid: str, kind: str, role: str, side: str, qty: int, price, watch=None,
               leg: Optional[PlanLeg] = None, resv: Optional[PlanSellReservation] = None,
               replaces: Optional[PlanOrderBook] = None, acct_before: Optional[int] = None,
               now: Optional[datetime] = None) -> PlanOrderBook:
    """보낼 때마다 한 줄 · 호출 전에 남긴다(호출자가 commit). 새 키를 쓴다."""
    line = PlanOrderBook(
        plan_id=plan.id, client_order_id=cid, kind=kind, role=role, side=side, qty=int(qty),
        price=float(price) if price is not None else None, watch_price=float(watch) if watch is not None else None,
        leg_id=leg.id if leg is not None else None, reservation_id=resv.id if resv is not None else None,
        replaces_id=replaces.id if replaces is not None else None, state=SENT_UNKNOWN, sent_at=now or utcnow(),
        acct_before=acct_before)
    s.add(line)
    await s.flush()
    return line


def mark_open(line: PlanOrderBook, toss_id: Optional[str]) -> None:
    line.toss_id, line.state, line.resolved_at = toss_id, OPEN, utcnow()


def mark_not_created(line: PlanOrderBook) -> None:
    line.state, line.resolved_at = NOT_CREATED, utcnow()


async def unresolved_lines(s, plan_id: int) -> list[PlanOrderBook]:
    return list(await s.scalars(select(PlanOrderBook).where(
        PlanOrderBook.plan_id == plan_id, PlanOrderBook.state.in_(UNRESOLVED)).order_by(PlanOrderBook.id)))


async def has_unresolved_for_leg(s, leg_id: int) -> bool:
    return await s.scalar(select(PlanOrderBook.id).where(
        PlanOrderBook.leg_id == leg_id, PlanOrderBook.state.in_(UNRESOLVED)).limit(1)) is not None


async def latest_open_line(s, leg_id: int) -> Optional[PlanOrderBook]:
    return await s.scalar(select(PlanOrderBook).where(
        PlanOrderBook.leg_id == leg_id, PlanOrderBook.state == OPEN).order_by(PlanOrderBook.id.desc()).limit(1))


async def exposure(s, plan_id: int) -> dict:
    """결과 모르는 줄의 수량. bound_new = 새로 걸다 모르는 손절(보호에 안 셈 · 그 수량은 다시 걸지 않고 묶음),
    unknown_modify = 수정하다 모르는 줄(옛 다리는 살아 있을 수 있음 · 넘침 검사에만 더함)."""
    bound_new = unknown_modify = 0
    for l in await unresolved_lines(s, plan_id):
        if l.role != "sl":
            continue
        if l.replaces_id is not None:
            unknown_modify += l.qty
        else:
            bound_new += l.qty
    return {"bound_new": bound_new, "unknown_modify": unknown_modify}


async def ensure_child_line(s, plan, leg: PlanLeg, child_id: str, qty: int) -> PlanOrderBook:
    """발동된 조건주문이 만든 자식 주문을 부모 줄 아래 적는다 (부모 조건주문 – 자식 주문 관계)."""
    existing = await s.scalar(select(PlanOrderBook).where(PlanOrderBook.toss_id == child_id, PlanOrderBook.plan_id == plan.id))
    if existing is not None:
        return existing
    parent = await s.scalar(select(PlanOrderBook).where(
        PlanOrderBook.leg_id == leg.id, PlanOrderBook.kind == "cond").order_by(PlanOrderBook.id.desc()).limit(1))
    line = PlanOrderBook(plan_id=plan.id, client_order_id=f"child-{leg.id}-{child_id}"[:40], kind="limit",
                         role="sell" if leg.role != "buy" else "buy", side="BUY" if leg.role == "buy" else "SELL",
                         qty=int(qty), price=leg.order_price, toss_id=child_id, parent_id=parent.id if parent else None,
                         leg_id=leg.id, state=OPEN, sent_at=utcnow(), resolved_at=utcnow())
    s.add(line)
    await s.flush()
    return line


# ─── 대조 (결과 모르는 주문의 판정은 이 한 곳) ────────────────────────────────

async def _load_lists(s, eng, plan) -> list[tuple[str, list[dict]]]:
    g = eng.gate
    return [("open_cond", await g.cond_open_list(s, plan.symbol)), ("open_order", await g.limit_open_list(s, plan.symbol)),
            ("closed_cond", await g.cond_closed_list(s, plan.symbol)), ("closed_order", await g.limit_closed_list(s, plan.symbol))]


async def _candidates(s, eng, plan, line: PlanOrderBook) -> list[dict]:
    """값 일치 후보(자동 연결 아님 · 사람에게 보여 줌). 이미 다른 줄 · 다리에 이어진 번호는 뺀다."""
    taken = {l.toss_id for l in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)) if l.toss_id}
    taken |= {b.toss_id for b in await s.scalars(select(PlanOrderBook).where(PlanOrderBook.plan_id == plan.id)) if b.toss_id}
    out = []
    try:
        for o in await eng.gate.cond_open_list(s, plan.symbol):
            if o and o.get("id") not in taken and o.get("qty") == line.qty and str(o.get("side") or "").upper() == line.side:
                out.append({"toss_id": o["id"], "qty": o.get("qty"), "watch": o.get("watch"), "order": o.get("order")})
    except Exception:  # noqa: BLE001 — 후보 보여 주기는 실패해도 판정을 막지 않는다
        pass
    return out


async def _to_human(s, eng, plan, line: PlanOrderBook, reason: str) -> None:
    line.state, line.resolved_at = NEEDS_HUMAN, None
    line.note = json.dumps({"reason": reason, "candidates": await _candidates(s, eng, plan, line)}, ensure_ascii=False, default=str)
    await eng._event(s, plan, "order_needs_human", f"{line.role} {line.client_order_id} · {reason}")
    await eng._halt(s, plan, f"결과를 모르는 주문이 있습니다 · {reason} · 화면에서 확인해 주십시오")


async def _link(s, eng, plan, line: PlanOrderBook, src: str, o: dict) -> None:
    """목록에서 clientOrderId 가 하나 맞았다 → 이음. 닫힌 목록이면 이어서 sync 가 체결 · 취소를 읽는다."""
    kind = "limit" if src.endswith("order") else "cond"
    line.toss_id, line.kind, line.state, line.resolved_at = o["id"], kind, OPEN, utcnow()
    resv = await s.get(PlanSellReservation, line.reservation_id) if line.reservation_id else None
    leg = await s.get(PlanLeg, line.leg_id) if line.leg_id else None
    if resv is not None:
        resv.order_ref, resv.uncertain = o["id"], False
    elif leg is not None and line.replaces_id is not None:
        old = await s.get(PlanOrderBook, line.replaces_id)
        leg.toss_id, leg.qty, leg.kind = o["id"], line.qty, kind
        if line.watch_price is not None:
            leg.watch_price, leg.order_price = line.watch_price, line.price
        if old is not None:
            old.state, old.resolved_at = CLOSED, utcnow()
        leg.status = "WATCHING"
    elif leg is not None and leg.status == "UNCERTAIN":
        leg.toss_id, leg.kind, leg.status = o["id"], kind, "WATCHING"
    await eng._event(s, plan, "order_linked", f"{line.role} {line.client_order_id} → {o['id']} ({src})")


async def _not_created(s, eng, plan, line: PlanOrderBook) -> None:
    mark_not_created(line)
    resv = await s.get(PlanSellReservation, line.reservation_id) if line.reservation_id else None
    leg = await s.get(PlanLeg, line.leg_id) if line.leg_id else None
    if resv is not None:
        resv.active, resv.uncertain = False, False          # 예약을 풀면 모자란 수량은 보호 다리로 다시 걸린다
    if leg is not None and line.replaces_id is None and leg.status == "UNCERTAIN":
        leg.status = "CANCELED"
    await eng._event(s, plan, "order_not_created", f"{line.role} {line.client_order_id}")


async def reconcile(s, eng, plan, now: Optional[datetime] = None) -> dict:
    """결과 모르는 주문을 판정하는 단 하나의 함수. 판정은 기다리는 시간(1) 뒤에만 · 설정(2 · 3)을 따른다."""
    from .engine import runtime_of  # noqa: F401  (순환 import 피함)

    now = now or eng.clock()
    out = {"linked": 0, "not_created": 0, "needs_human": 0, "waiting": 0}
    lines = await unresolved_lines(s, plan.id)
    unknown = [l for l in lines if l.state == SENT_UNKNOWN]
    if unknown:
        due = [l for l in unknown if (now - (l.sent_at or now)).total_seconds() >= settle_sec()]
        out["waiting"] = len(unknown) - len(due)             # 기다리는 시간 안에는 없음으로 단정하지 않는다
        if due:
            searchable = list_searchable()
            lists = await _load_lists(s, eng, plan) if searchable else []
            for l in due:
                if not searchable:
                    await _to_human(s, eng, plan, l, "목록에서 clientOrderId 로 찾을 수 없는 설정(U6 확인 전)")
                    out["needs_human"] += 1
                    continue
                matches = [(src, o) for src, items in lists for o in items if o and o.get("client_id") == l.client_order_id]
                if len(matches) > 1:
                    await _to_human(s, eng, plan, l, "같은 clientOrderId 가 목록에 둘 이상")
                    out["needs_human"] += 1
                elif len(matches) == 1:
                    await _link(s, eng, plan, l, *matches[0])
                    out["linked"] += 1
                elif list_paging_known():
                    await _not_created(s, eng, plan, l)
                    out["not_created"] += 1
                else:
                    await _to_human(s, eng, plan, l, "목록 쪽 나눔을 몰라 목록에 없다는 것을 안 만들어짐 근거로 쓰지 않음")
                    out["needs_human"] += 1
    # 사람이 확인할 때까지 ⑨ 긴급 알림을 되풀이한다 · 매수는 계좌 보유가 늘면 따로 경보 (체결 줄은 만들지 않는다)
    for l in await s.scalars(select(PlanOrderBook).where(PlanOrderBook.plan_id == plan.id, PlanOrderBook.state == NEEDS_HUMAN)):
        await eng._alert_once(s, plan, f"unknown_order:{l.id}", "critical", "결과 모르는 주문 확인 필요",
                              f"{l.role} 주문 {l.qty}주의 결과를 모릅니다. 그 수량은 묶어 두었습니다. 화면에서 「체결 n주 / 안 만들어짐」을 정해 주십시오.",
                              every_sec=REPEAT_ALERT_SEC)
        if l.role == "buy" and l.acct_before is not None:
            now_q = await eng._acct_now(s, plan)
            if now_q is not None and now_q > l.acct_before:
                await eng._alert_once(s, plan, f"unknown_buy_holdings:{l.id}", "critical", "매수 체결 가능성",
                                      f"계좌 보유가 {now_q - l.acct_before}주 늘었습니다. 화면에서 체결 수량을 확정하면 손절을 겁니다 (자동으로 적지 않음).",
                                      every_sec=REPEAT_ALERT_SEC)
    await s.flush()
    return out


async def check_child(s, eng, plan, leg: PlanLeg, g: dict, ref: str, out: dict) -> None:
    """발동된 조건주문의 자식 주문 확인(부모 – 자식 관계는 장부에). 닫힘이 확인될 때만 예약을 푼다. 모르면 유지 + 알림."""
    from . import sizing

    child = g.get("order_id")
    info = None
    if child:
        try:
            info = await eng.gate.limit_get(s, child)
        except Exception:  # noqa: BLE001
            return
        await ensure_child_line(s, plan, leg, child, leg.qty)
    closed_states = ("CANCELED", "EXPIRED", "REJECTED", "FILLED")
    if info is not None:
        if info.get("status") == "OPEN":
            return
        if info.get("status") not in closed_states:
            await eng._alert_once(s, plan, f"unknown_child:{leg.id}", "warning", "발동된 주문 상태 모름",
                                  f"{leg.role}{leg.seq} 자식 주문의 상태를 알 수 없어 예약을 유지합니다.", every_sec=REPEAT_ALERT_SEC)
            return
    elif g.get("status") not in ("CANCELED", "EXPIRED", "REJECTED"):
        if g.get("status") == "UNKNOWN":
            await eng._alert_once(s, plan, f"unknown_cond:{leg.id}", "warning", "발동된 주문 상태 모름",
                                  f"{leg.role}{leg.seq} 조건주문의 상태를 알 수 없어 예약을 유지합니다.", every_sec=REPEAT_ALERT_SEC)
        return
    f = int((info or g).get("filled") or 0)
    if f:
        out["sold"] += await eng._record_fill(s, plan, "SELL", ref, f, (info or g).get("avg"))
    await sizing.release(s, plan.id, ref)
    leg.status = "FILLED" if (info or {}).get("status") == "FILLED" else "CANCELED"
    if child:
        cl = await s.scalar(select(PlanOrderBook).where(PlanOrderBook.toss_id == child, PlanOrderBook.plan_id == plan.id))
        if cl is not None:
            cl.state, cl.resolved_at = CLOSED, utcnow()
    await eng._event(s, plan, "triggered_closed", f"{leg.role}{leg.seq} 체결 {f}")


async def on_missing(s, eng, plan, leg: PlanLeg) -> None:
    """단건 조회가 빈 값이면 바로 CANCELED 로 두지 않는다. 열린 · 닫힌 목록에서 그 번호를 찾고, 못 찾으면 사람 확인으로 보낸다."""
    from . import sizing

    found = None
    try:
        for src, items in await _load_lists(s, eng, plan):
            for o in items:
                if o and o.get("id") == leg.toss_id:
                    found = (src, o)
    except Exception:  # noqa: BLE001
        pass
    if found is not None and found[0].startswith("closed"):
        if leg.status == "TRIGGERED":
            await sizing.release(s, plan.id, leg.toss_id)
        leg.status = "CANCELED"
        await eng._event(s, plan, "leg_closed_in_list", f"{leg.role}{leg.seq}")
        return
    if found is not None:
        return                                              # 열린 목록에 있다 → 단건 조회만 비었다 · 그대로 둔다
    line = await latest_open_line(s, leg.id)
    if line is None:
        line = PlanOrderBook(plan_id=plan.id, client_order_id=f"missing-{leg.id}", kind=leg.kind, role=leg.role,
                             side=leg.side, qty=leg.qty, price=leg.order_price, toss_id=leg.toss_id, leg_id=leg.id,
                             state=OPEN, sent_at=utcnow())
        s.add(line)
        await s.flush()
    line.state, line.note = NEEDS_HUMAN, json.dumps({"reason": "단건 조회가 비었고 목록에도 없음", "candidates": []}, ensure_ascii=False)
    leg.status = "UNCERTAIN"                                # 보호에 세지 않고 그 수량을 묶는다
    await eng._event(s, plan, "leg_missing", f"{leg.role}{leg.seq} · 사람 확인으로 보냄")
    await eng._halt(s, plan, f"{leg.role}{leg.seq} 주문이 조회되지 않습니다 · 화면에서 확인해 주십시오")


# ─── 사람이 확정 (DB 만 · 토스를 부르지 않는다) ────────────────────────────────

class ResolveError(Exception):
    pass


async def human_resolve(s, plan, line_id: int, decision: str, *, filled_qty: Optional[int] = None,
                        toss_id: Optional[str] = None, actor: str = "대표") -> PlanOrderBook:
    """「체결 n주 / 안 만들어짐 / 열려 있음(번호)」 확정. 체결은 사람이 정한 수량만 장부(PlanFill)에 적는다."""
    from . import state as st

    line = await s.get(PlanOrderBook, line_id)
    if line is None or line.plan_id != plan.id:
        raise ResolveError("주문 줄을 찾을 수 없습니다")
    if line.state not in UNRESOLVED:
        raise ResolveError("이미 확인된 줄입니다")
    resv = await s.get(PlanSellReservation, line.reservation_id) if line.reservation_id else None
    leg = await s.get(PlanLeg, line.leg_id) if line.leg_id else None
    note = json.loads(line.note or "{}")
    note["human"] = {"decision": decision, "actor": actor, "at": utcnow().isoformat(), "filled_qty": filled_qty}
    if decision == "not_created":
        mark_not_created(line)
        if resv is not None:
            resv.active, resv.uncertain = False, False
        if leg is not None and line.replaces_id is None and leg.status == "UNCERTAIN":
            leg.status = "CANCELED"
    elif decision == "filled":
        if not filled_qty or filled_qty <= 0 or filled_qty > line.qty:
            raise ResolveError("체결 수량은 1 이상 주문 수량 이하여야 합니다")
        side = "BUY" if line.side == "BUY" else "SELL"
        s.add(PlanFill(plan_id=plan.id, side=side, qty=int(filled_qty), price=float(line.price or 0),
                       order_ref=f"human{line.id}", fill_seq=int(filled_qty)))
        line.state, line.filled_qty, line.resolved_at = CLOSED, int(filled_qty), utcnow()
        if resv is not None:
            resv.active, resv.uncertain = False, False
        if leg is not None:
            if line.replaces_id is not None:
                leg.status = "CANCELED"                      # 수정으로 보낸 새 주문이 체결됨 → 그 다리는 끝 (남은 수량은 보호 다리로 다시 걸림)
                old = await s.get(PlanOrderBook, line.replaces_id)
                if old is not None:
                    old.state, old.resolved_at = CLOSED, utcnow()
            else:
                leg.status = "FILLED" if line.role == "buy" else "CANCELED"
    elif decision == "open":
        if not toss_id:
            raise ResolveError("열려 있다면 토스 주문 번호가 필요합니다")
        mark_open(line, toss_id)
        if resv is not None:
            resv.order_ref, resv.uncertain = toss_id, False
        if leg is not None:
            if line.replaces_id is not None:
                leg.toss_id, leg.qty = toss_id, line.qty
                old = await s.get(PlanOrderBook, line.replaces_id)
                if old is not None:
                    old.state, old.resolved_at = CLOSED, utcnow()
            elif leg.status == "UNCERTAIN":
                leg.toss_id, leg.status = toss_id, "WATCHING"
    else:
        raise ResolveError("알 수 없는 결정입니다")
    line.note = json.dumps(note, ensure_ascii=False, default=str)
    await st.event(s, plan.id, "order_human_resolved", f"{line.role} {line.client_order_id} · {decision}")
    await s.flush()
    return line
