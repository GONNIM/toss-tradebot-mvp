"""주문 장부 · 결과 모르는 주문 대조 · 계획서 5절 10항 · 7-2 (1116-01 · Fable 재설계 · 사용자 11/18 승인).

「이 주문이 만들어졌는가 · 얼마나 체결됐는가」 를 모르는 경우의 판정은 **이 모듈 한 곳**에만 있다.
엔진은 보낼 때마다 장부 한 줄(PlanOrderBook)을 남기고, 모르게 끝난 줄 · 단건 조회가 빈 값인 다리와 예약 ·
발동된 조건주문의 자식 주문 상태를 이 모듈의 함수(reconcile · on_missing · on_missing_reservation · check_child ·
after_send_failure · human_resolve)에 맡긴다.

규칙
1. 낸 뒤 `PLAN_ORDER_SETTLE_SEC`(기본 90초) 안에는 「없음」으로 단정하지 않는다.
2. 목록에서 clientOrderId 로 찾을 수 있는지는 설정(`PLAN_ORDER_LIST_SEARCHABLE` · 기본 꺼짐 = 못 찾음).
   꺼져 있으면 모르는 주문은 모두 「그 수량 묶음 + 사람 확인」이다. U6(소액 시험 첫 순서) 결과가 나오면 설정만 바꾼다.
3. 목록 쪽 나눔을 아는지는 설정(`PLAN_ORDER_LIST_PAGING_KNOWN` · 기본 꺼짐). 모르는 동안에는 목록에 없다는 것을 「안 만들어짐」 근거로 쓰지 않는다.
4. 같은 clientOrderId 가 둘이면 자동 연결하지 않고 사람에게 간다. 수량 · 가격이 같다는 값 일치로는 자동 연결하지 않고 후보로만 보여 준다.
5. 계좌 보유 변화는 체결의 근거가 아니다(상한 검사 · 경보에만 쓴다). 체결 줄(PlanFill)은 토스 주문 상태 또는 사람의 확정으로만 만든다.
6. 모름인 동안 그 수량은 묶는다(손절은 그 수량을 뺀 나머지 보호를 계속 건다). ⑨ 긴급 알림을 되풀이해 보낸다.
7. 부모 조건주문 – 자식 주문 관계(발동된 조건주문이 만든 주문)를 장부에 적는다.
8. 수정은 「옛 줄 열림 + 새 줄 보냄-모름」 이 함께 있을 수 있다. 옛 다리가 닫힌 것으로 읽히면(옛 주문이 새 줄로 바뀐 경우) 새 줄을 묶인 수량으로 센다.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from backend.execution.exceptions import OrderRejected, RateLimitExceeded

from .models import PlanFill, PlanLeg, PlanOrderBook, PlanSellReservation, utcnow

logger = logging.getLogger(__name__)

SENT_UNKNOWN, OPEN, CLOSED, NOT_CREATED, NEEDS_HUMAN = "sent_unknown", "open", "closed", "not_created", "needs_human"
UNRESOLVED = (SENT_UNKNOWN, NEEDS_HUMAN)
REPEAT_ALERT_SEC = 600
MISS_CONFIRM_STEPS = 2          # 단건 조회가 연속으로 이만큼 비어야 사람 확인으로 보낸다 (한 번 빈 것은 일시 오류일 수 있음)
OPEN_GRACE_SEC = 600            # 사람이 「열려 있음」 으로 확정한 번호는 이 시간 동안 빈 조회로 다시 묻지 않는다
TOSS_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")          # 토스 번호는 영문 · 숫자 · - 만


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


def definitely_not_created(exc: Exception) -> bool:
    """토스가 분명히 받지 않은 실패(거절 · 한도 초과)인가. 그 밖(시간 초과 · 5xx · 번호 없는 응답)은 만들어졌는지 모른다."""
    return isinstance(exc, (OrderRejected, RateLimitExceeded))


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


async def after_send_failure(s, eng, plan, leg: PlanLeg, role: str, seq: int, exc: Exception, line: Optional[PlanOrderBook]):
    """보낸 뒤 오류가 났을 때의 판정 · 분명히 거절됐으면 지우고, 결과를 모르면 「확인 대기」 로 두고 대조에 맡긴다(같은 키로 다시 내지 않음)."""
    if definitely_not_created(exc):
        if line is not None:
            mark_not_created(line)
        await s.delete(leg)
        await s.commit()
        await eng._event(s, plan, "leg_register_fail", f"{role}{seq} {exc.__class__.__name__}")
        return None
    leg.status = "UNCERTAIN"
    await eng._event(s, plan, "leg_uncertain", f"{role}{seq} {exc.__class__.__name__} · 확인 대기")
    await s.commit()
    return None


async def unresolved_lines(s, plan_id: int) -> list[PlanOrderBook]:
    return list(await s.scalars(select(PlanOrderBook).where(
        PlanOrderBook.plan_id == plan_id, PlanOrderBook.state.in_(UNRESOLVED)).order_by(PlanOrderBook.id)))


async def has_unresolved_for_leg(s, leg_id: int) -> bool:
    return await s.scalar(select(PlanOrderBook.id).where(
        PlanOrderBook.leg_id == leg_id, PlanOrderBook.state.in_(UNRESOLVED)).limit(1)) is not None


async def latest_open_line(s, leg_id: int) -> Optional[PlanOrderBook]:
    return await s.scalar(select(PlanOrderBook).where(
        PlanOrderBook.leg_id == leg_id, PlanOrderBook.state == OPEN,
        PlanOrderBook.client_order_id.not_like("missing-%")).order_by(PlanOrderBook.id.desc()).limit(1))


async def exposure(s, plan_id: int) -> dict:
    """결과 모르는 손절 줄의 수량.
    bound_new = 보호에 안 세고 그 수량을 묶는 줄: 새로 걸다 모르는 줄 · 다리가 닫히거나 사라진 채 남은 수정 줄 · 조회가 비어 사람 확인으로 간 다리.
    unknown_modify = 옛 다리가 아직 살아 있는 수정 줄(넘침 검사에만 더한다 · 보호 수량에는 확인된 옛 다리만 센다)."""
    bound_new = unknown_modify = 0
    by_leg: dict = {}
    for l in await unresolved_lines(s, plan_id):
        if l.role != "sl":
            continue
        if l.leg_id is None:
            bound_new += l.qty
        else:
            by_leg.setdefault(l.leg_id, []).append(l)
    for leg_id, group in by_leg.items():               # 같은 다리의 모름 줄은 수량을 한 번만 센다 (가장 큰 줄)
        leg = await s.get(PlanLeg, leg_id)
        q = max(l.qty for l in group)
        if all(l.replaces_id is not None for l in group) and leg is not None and leg.status in ("WATCHING", "TRIGGERED"):
            unknown_modify += q                         # 옛 다리가 살아 있다 → 넘침 검사에만 더한다
        else:
            bound_new += q                              # 옛 다리가 닫혔거나 사라졌거나 조회가 빈 채 → 그 수량을 묶는다
    return {"bound_new": bound_new, "unknown_modify": unknown_modify}


async def bound_seqs(s, plan_id: int) -> set[int]:
    """결과 모르는 줄이 걸린 손절 다리 번호 · 이 번호는 새로 등록하지 않는다 (중복 등록 방지)."""
    out: set[int] = set()
    for l in await unresolved_lines(s, plan_id):
        if l.role == "sl" and l.leg_id:
            leg = await s.get(PlanLeg, l.leg_id)
            if leg is not None:
                out.add(leg.seq)
    return out


async def modifying_leg_ids(s, plan_id: int) -> set[int]:
    return {l.leg_id for l in await unresolved_lines(s, plan_id) if l.role == "sl" and l.replaces_id is not None and l.leg_id}


async def ensure_child_line(s, plan, leg: PlanLeg, child_id: str, qty: int) -> PlanOrderBook:
    """발동된 조건주문이 만든 자식 주문을 부모 줄 아래 적는다 (부모 조건주문 – 자식 주문 관계)."""
    existing = await s.scalar(select(PlanOrderBook).where(PlanOrderBook.toss_id == child_id, PlanOrderBook.plan_id == plan.id))
    if existing is not None:
        return existing
    parent = await s.scalar(select(PlanOrderBook).where(
        PlanOrderBook.leg_id == leg.id, PlanOrderBook.kind == "cond").order_by(PlanOrderBook.id.desc()).limit(1))
    line = PlanOrderBook(plan_id=plan.id, client_order_id=f"child-{leg.id}-{child_id}"[:48], kind="limit",
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


async def _apply_open(s, line: PlanOrderBook, leg: Optional[PlanLeg], resv: Optional[PlanSellReservation], toss_id: str,
                      kind: str) -> None:
    """「열려 있음」 으로 이을 때 장부 · 다리 · 예약을 한 방식으로 맞춘다 (대조가 이을 때와 사람이 확정할 때 같다)."""
    line.toss_id, line.kind, line.state, line.resolved_at = toss_id, kind, OPEN, utcnow()
    if resv is not None:
        resv.order_ref, resv.uncertain = toss_id, False
    if leg is None:
        return
    if line.replaces_id is not None:
        old = await s.get(PlanOrderBook, line.replaces_id)
        if old is not None:
            old.state, old.resolved_at = CLOSED, utcnow()
    if line.replaces_id is not None or leg.status == "UNCERTAIN" or line.client_order_id.startswith("missing-"):
        leg.toss_id, leg.kind, leg.status = toss_id, kind, "WATCHING"
        if line.replaces_id is not None:               # 수정 줄이면 새 값(수량 · 감시가 · 주문가 · 고유 키)으로 맞춘다
            leg.qty = line.qty
            if line.watch_price is not None:
                leg.watch_price, leg.order_price = line.watch_price, line.price
            leg.client_order_id = line.client_order_id


async def _link(s, eng, plan, line: PlanOrderBook, src: str, o: dict) -> None:
    kind = "limit" if src.endswith("order") else "cond"
    resv = await s.get(PlanSellReservation, line.reservation_id) if line.reservation_id else None
    leg = await s.get(PlanLeg, line.leg_id) if line.leg_id else None
    await _apply_open(s, line, leg, resv, o["id"], kind)
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
    now = now or eng.clock()
    out = {"linked": 0, "not_created": 0, "needs_human": 0, "waiting": 0}
    lines = await unresolved_lines(s, plan.id)
    unknown = [l for l in lines if l.state == SENT_UNKNOWN]
    if unknown:
        due = [l for l in unknown if (now - (l.sent_at or now)).total_seconds() >= settle_sec()]
        out["waiting"] = len(unknown) - len(due)             # 기다리는 시간 안에는 없음으로 단정하지 않는다
        if due:
            searchable = list_searchable()
            lists: list = []
            if searchable:
                try:
                    lists = await _load_lists(s, eng, plan)
                except Exception as exc:  # noqa: BLE001 — 목록을 못 읽으면 이 줄들만 미루고 걸음 전체는 계속한다
                    await eng._alert_once(s, plan, "list_read_fail", "warning", "주문 목록 읽기 실패",
                                          f"결과 모르는 주문 {len(due)}건의 확인을 미룹니다 ({exc.__class__.__name__}).", every_sec=REPEAT_ALERT_SEC)
                    due, searchable = [], False
                    out["waiting"] = len(unknown)
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


async def _find_in_lists(s, eng, plan, toss_id: Optional[str]):
    for src, items in await _load_lists(s, eng, plan):
        for o in items:
            if o and o.get("id") == toss_id:
                return src, o
    return None


def _bump_miss(plan, key: str) -> int:
    from .engine import runtime_of, set_runtime

    m = dict(runtime_of(plan).get("miss") or {})
    m[key] = int(m.get(key, 0)) + 1
    set_runtime(plan, miss=m)
    return m[key]


def clear_miss(plan, key: str) -> None:
    """조회가 다시 읽히면 연속 빈 조회 횟수를 지운다."""
    from .engine import runtime_of, set_runtime

    m = dict(runtime_of(plan).get("miss") or {})
    if key in m:
        m.pop(key)
        set_runtime(plan, miss=m)


async def _new_missing_line(s, plan, *, leg: Optional[PlanLeg], resv: Optional[PlanSellReservation], role: str, side: str,
                            qty: int, price, toss_id: Optional[str], reason: str) -> Optional[PlanOrderBook]:
    """단건 조회가 빈 값일 때의 사람 확인 줄 · 수정 줄을 재사용하지 않고 원래 다리 수량 그대로 따로 둔다."""
    ident = f"{'r' + str(resv.id) if resv is not None else 'l' + str(leg.id)}"
    same = list(await s.scalars(select(PlanOrderBook).where(
        PlanOrderBook.plan_id == plan.id, PlanOrderBook.client_order_id.like(f"missing-{ident}-%")).order_by(PlanOrderBook.id)))
    for e in same:                                      # 미확정 같은 이름 줄이 하나라도 있으면 새로 쌓지 않는다
        if e.state in UNRESOLVED:
            return e
    now = utcnow()
    for e in same:                                      # 사람이 방금 「열려 있음」 으로 확정한 번호는 한동안 다시 묻지 않는다
        if e.state == OPEN and e.resolved_at is not None and (now - e.resolved_at).total_seconds() < OPEN_GRACE_SEC:
            return None
    cnt = len(same)
    line = PlanOrderBook(plan_id=plan.id, client_order_id=f"missing-{ident}-{cnt + 1}", kind="cond" if leg is not None else "limit",
                         role=role, side=side, qty=int(qty), price=price, toss_id=toss_id,
                         leg_id=leg.id if leg is not None else None, reservation_id=resv.id if resv is not None else None,
                         state=NEEDS_HUMAN, sent_at=utcnow(), note=json.dumps({"reason": reason, "candidates": []}, ensure_ascii=False))
    s.add(line)
    await s.flush()
    return line


async def _record_closed(s, eng, plan, side: str, ref: str, o: dict, qty: int) -> int:
    """닫힌 목록에서 찾았을 때 그 항목이 말하는 체결 수량을 장부에 적는다 (전량 체결인데 수량 칸이 없으면 주문 수량)."""
    f = int(o.get("filled") or 0)
    if not f and str(o.get("status") or "").upper() == "FILLED":
        f = int(qty)
    if f:
        return await eng._record_fill(s, plan, side, ref, f, o.get("avg") or o.get("price"))
    return 0


async def on_missing(s, eng, plan, leg: PlanLeg) -> None:
    """단건 조회가 빈 값인 다리. 바로 CANCELED 로 두지 않는다 · 열린 · 닫힌 목록에서 번호를 찾고 못 찾으면 사람 확인(그 수량을 묶음)."""
    from . import sizing

    if _bump_miss(plan, f"l{leg.id}") < MISS_CONFIRM_STEPS:
        return                                              # 한 번 빈 조회로는 아직 아무것도 바꾸지 않는다
    try:
        found = await _find_in_lists(s, eng, plan, leg.toss_id)
    except Exception as exc:  # noqa: BLE001 — 목록을 못 읽으면 이 다리만 미룬다
        await eng._alert_once(s, plan, f"missing_list_fail:{leg.id}", "warning", "주문 목록 읽기 실패",
                              f"{leg.role}{leg.seq} 조회가 비어 있어 목록으로 확인하려 했지만 목록을 읽지 못했습니다 ({exc.__class__.__name__}).",
                              every_sec=REPEAT_ALERT_SEC)
        return
    if found is not None and found[0].startswith("closed"):
        side = "BUY" if leg.role == "buy" else "SELL"
        await _record_closed(s, eng, plan, side, leg.toss_id, found[1], leg.qty)       # 체결 수량도 장부에 (닫힌 항목이 말하는 만큼)
        if leg.status == "TRIGGERED":
            await sizing.release(s, plan.id, leg.toss_id)
        leg.status = "FILLED" if str(found[1].get("status") or "").upper() == "FILLED" else "CANCELED"
        await eng._event(s, plan, "leg_closed_in_list", f"{leg.role}{leg.seq}")
        return
    if found is not None:
        return                                              # 열린 목록에 있다 → 단건 조회만 비었다 · 그대로 둔다
    made = await _new_missing_line(s, plan, leg=leg, resv=None, role=leg.role, side=leg.side, qty=leg.qty, price=leg.order_price,
                                   toss_id=leg.toss_id, reason="단건 조회가 비었고 목록에도 없음")
    if made is None:
        return                                              # 사람이 방금 열려 있음으로 확정한 번호
    leg.status = "UNCERTAIN"                                # 보호에 세지 않고 그 수량을 묶는다
    await eng._event(s, plan, "leg_missing", f"{leg.role}{leg.seq} · 사람 확인으로 보냄")
    await eng._halt(s, plan, f"{leg.role}{leg.seq} 주문이 조회되지 않습니다 · 화면에서 확인해 주십시오")


async def on_missing_reservation(s, eng, plan, r: PlanSellReservation) -> None:
    """접수된 매도의 단건 조회가 빈 값. 예약을 바로 풀지 않는다 · 목록에서 확인하고 못 찾으면 예약을 유지한 채 사람 확인."""
    if _bump_miss(plan, f"r{r.id}") < MISS_CONFIRM_STEPS:
        return
    try:
        found = await _find_in_lists(s, eng, plan, r.order_ref)
    except Exception as exc:  # noqa: BLE001
        await eng._alert_once(s, plan, f"missing_resv_list_fail:{r.id}", "warning", "주문 목록 읽기 실패",
                              f"접수된 매도 조회가 비어 있어 목록으로 확인하려 했지만 읽지 못했습니다 ({exc.__class__.__name__}).",
                              every_sec=REPEAT_ALERT_SEC)
        return
    if found is not None and found[0].startswith("closed"):
        await _record_closed(s, eng, plan, "SELL", r.order_ref, found[1], r.qty)
        r.active = False
        return
    if found is not None:
        return
    made = await _new_missing_line(s, plan, leg=None, resv=r, role="sell", side="SELL", qty=r.qty, price=r.order_price,
                                   toss_id=r.order_ref, reason="접수된 매도의 단건 조회가 비었고 목록에도 없음")
    if made is None:
        return
    await eng._halt(s, plan, "접수된 매도 주문이 조회되지 않습니다 · 예약을 유지합니다 · 화면에서 확인해 주십시오")


# ─── 사람이 확정 (DB 만 · 토스를 부르지 않는다) ────────────────────────────────

class ResolveError(Exception):
    pass


async def human_resolve(s, plan, line_id: int, decision: str, *, filled_qty: Optional[int] = None,
                        toss_id: Optional[str] = None, remainder_cancelled: bool = False, kind: Optional[str] = None,
                        actor: str = "대표") -> PlanOrderBook:
    """「체결 n주 / 안 만들어짐 / 열려 있음(번호)」 확정. 체결은 사람이 정한 수량만 장부(PlanFill)에 적는다.
    일부만 체결(n < 주문 수량)이면 남은 주문이 살아 있을 수 있으므로 「남은 주문을 토스 앱에서 취소했음」 확인이 있어야 확정한다
    (남은 주문을 계속 추적하려면 「열려 있음」 으로 토스 번호를 넣는다 · 그러면 실제 체결 수량은 주문 상태에서 읽는다)."""
    from . import state as st
    from .engine import set_runtime

    line = await s.get(PlanOrderBook, line_id)
    if line is None or line.plan_id != plan.id:
        raise ResolveError("주문 줄을 찾을 수 없습니다")
    if line.state not in UNRESOLVED:
        raise ResolveError("이미 확인된 줄입니다")
    resv = await s.get(PlanSellReservation, line.reservation_id) if line.reservation_id else None
    leg = await s.get(PlanLeg, line.leg_id) if line.leg_id else None
    note = json.loads(line.note or "{}")
    note["human"] = {"decision": decision, "actor": actor, "at": utcnow().isoformat(), "filled_qty": filled_qty,
                     "remainder_cancelled": remainder_cancelled}
    tp1_filled = False
    if decision == "not_created":
        mark_not_created(line)
        if resv is not None:
            resv.active, resv.uncertain = False, False
        if leg is not None and line.replaces_id is None and leg.status == "UNCERTAIN":
            leg.status = "CANCELED"
    elif decision == "filled":
        if not filled_qty or filled_qty <= 0 or filled_qty > line.qty:
            raise ResolveError("체결 수량은 1 이상 주문 수량 이하여야 합니다")
        if filled_qty < line.qty and not remainder_cancelled:
            raise ResolveError("일부만 체결이면 남은 주문을 토스 앱에서 취소했다는 확인이 필요합니다 "
                               "(남은 주문을 계속 추적하려면 「열려 있음」 으로 토스 주문 번호를 넣어 주십시오)")
        side = "BUY" if line.side == "BUY" else "SELL"
        s.add(PlanFill(plan_id=plan.id, side=side, qty=int(filled_qty), price=float(line.price or 0),
                       order_ref=f"human{line.id}", fill_seq=int(filled_qty)))
        line.state, line.filled_qty, line.resolved_at = CLOSED, int(filled_qty), utcnow()
        if resv is not None:
            resv.active, resv.uncertain = False, False
            tp1_filled = resv.kind == "tp1_watch"
        if leg is not None:
            if line.replaces_id is not None:
                leg.status = "CANCELED"                      # 수정으로 보낸 새 주문이 체결됨 → 그 다리는 끝 (남은 수량은 보호 다리로 다시 걸림)
                old = await s.get(PlanOrderBook, line.replaces_id)
                if old is not None:
                    old.state, old.resolved_at = CLOSED, utcnow()
            elif line.role == "tp1":
                leg.status, tp1_filled = "FILLED", True       # TP1 체결 확정 → 추적 전환으로 이어진다 (TP1 을 다시 내지 않는다)
            else:
                leg.status = "FILLED" if line.role == "buy" else "CANCELED"
    elif decision == "open":
        if not toss_id or not TOSS_ID_RE.match(toss_id):
            raise ResolveError("토스 주문 번호가 필요합니다 (영문 · 숫자 · - 만)")
        k = kind if kind in ("cond", "limit") else line.kind
        await _apply_open(s, line, leg, resv, toss_id, "limit" if k == "limit" else "cond")
    else:
        raise ResolveError("알 수 없는 결정입니다")
    if tp1_filled:
        set_runtime(plan, tp1_filled_human=True)             # 다음 걸음에 TP1 체결 처리(_on_tp1_filled)를 탄다
    line.note = json.dumps(note, ensure_ascii=False, default=str)
    await st.event(s, plan.id, "order_human_resolved", f"{line.role} {line.client_order_id} · {decision}")
    await s.flush()
    return line
