"""계획 실행 엔진 · 계획서 5 · 6-1 · 7 · 8절.

다리 등록 · 수정 · 취소는 모두 DirectionGate(brokers.py) 를 거친다. 이 파일은 토스를 직접 부르지 않는다.
한 번의 `tick_plan` 이 한 계획의 상태를 한 걸음 진행한다(체결 읽기 → 상태별 일 → 불변식 검사).

[부분 구현] 아래는 계획서에 값이 없어 단순하게 둔 곳이다 (보고서 「계획서와 다르게 한 곳」):
- 진입 마감 처리(ENTRY_RETRY): 마감 시각 · 창 끝 시각은 계획 값(params)에서 받는다. v4 7절 값 규칙은 이 저장소에 없다.
- 거래일 계산은 주말 + 받은 휴장일만 건너뛴다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from backend.execution.exceptions import ExecutionError, OrderRejected

from . import sanity
from . import sessions as sess
from . import sizing, state
from .brokers import DirectionGate, GateResult
from .models import Plan, PlanFill, PlanLeg, PlanLegPending, PlanSellReservation, utcnow
from .pricing import D, ceil_tick, floor_tick, order_price_from_watch, sell_order
from .sessions import Values
from .switches import content_hash_of

logger = logging.getLogger(__name__)

SELL_EXPIRE_DAYS = 90            # 매도 다리 만료 = 등록일 + 90일 (6-1)
EXPIRE_EXTEND_BELOW_DAYS = 10    # 남은 기간이 10일 아래면 같은 값으로 수정해 연장
MAX_REJECT_LOOPS = 3             # 같은 다리 거절 · 다시 걸기 3번 → HALTED (6-1)
MAX_LEG_ERRORS = 3               # 같은 다리 오류 3번 → HALTED (9절)
REPRICE_AFTER_SEC = 10           # 접수된 매도가 주문가 아래로 내려가면 10초 안에 다시 내기 (7-4)

Notify = Callable[[str, str, str, str], Awaitable[Any]]   # (level, title, body, category)


def params_of(plan: Plan) -> dict:
    try:
        return json.loads(plan.params_json or "{}")
    except ValueError:
        return {}


def set_params(plan: Plan, p: dict) -> None:
    plan.params_json = json.dumps(p, ensure_ascii=False, default=str)


APPROVAL_KEYS = ("symbol", "mode", "budget_usd", "buy_watch", "buy_order", "qty", "tp1_watch", "tp1_order",
                 "ladder_pcts", "announce_at", "entry_close_at", "entry_window_end", "adopt")


def approval_values(plan: Plan) -> dict:
    p = params_of(plan)
    v = {k: p.get(k) for k in APPROVAL_KEYS if k in p}
    v["symbol"], v["mode"] = plan.symbol, plan.mode
    return v


def refresh_hash(plan: Plan) -> None:
    plan.content_hash = content_hash_of(approval_values(plan))


class PlanEngine:
    def __init__(
        self, gate: DirectionGate, *, notify: Notify,
        clock: Callable[[], datetime] = utcnow,
        limit_factor: Callable[[datetime], Optional[Decimal]] = lambda now: Decimal("0.98"),
        regular_window: Callable[[datetime], Optional[tuple[datetime, datetime]]] = lambda now: None,
        switches: Optional[Callable[[], dict]] = None,
        kill_state: Callable[[], tuple[bool, bool]] = lambda: (False, True),
        holidays: Callable[[], frozenset] = lambda: frozenset(),
    ):
        from .switches import read_switches

        self.gate = gate
        self._notify = notify
        self.clock = clock
        self.limit_factor = limit_factor
        self.regular_window = regular_window
        self.switches = switches or read_switches
        self.kill_state = kill_state
        self.holidays = holidays

    # ───────────────── 알림 · 기록 ─────────────────
    async def _alert(self, plan: Plan, level: str, title: str, body: str) -> None:
        """실전 · 시험 = ⑨ 실주문 · 모의 = 시스템 범주에 「모의 시험」 표시 (1절 9항)."""
        try:
            if plan.mode == "paper":
                await self._notify(level, f"[모의 시험] {title}", f"[모의 시험] 계획 번호 {plan.id}\n{body}", "system")
            else:
                await self._notify(level, title, f"계획 번호 {plan.id}\n{body}", "execution")
        except Exception as exc:  # noqa: BLE001 — 알림 실패가 주문 흐름을 막지 않는다
            logger.warning("[plan] 알림 실패 · %s", exc.__class__.__name__)

    async def _event(self, s, plan: Plan, kind: str, detail: str = "") -> None:
        await state.event(s, plan.id, kind, detail)

    async def _halt(self, s, plan: Plan, reason: str, *, urgent: bool = True) -> None:
        if await state.halt(s, plan, reason):
            if urgent:
                await self._alert(plan, "critical", "계획 정지", reason)

    def _cid(self, plan: Plan, role: str, seq: int) -> str:
        p = params_of(plan)
        n = int(p.get("cid_n", 0)) + 1
        p["cid_n"] = n
        set_params(plan, p)
        return f"{plan.id}-{role}{seq}-{n}"[:36]

    def _expire(self, days: int = SELL_EXPIRE_DAYS) -> str:
        return (self.clock() + timedelta(days=days)).strftime("%Y-%m-%d")

    def _live_on(self, plan: Plan) -> bool:
        sw = self.switches()
        return bool(sw.get("paper" if plan.mode == "paper" else "live"))

    # ───────────────── 계획 만들기 · 승인 ─────────────────
    async def create_draft(self, s, *, symbol: str, mode: str, params: dict, source: str = "manual") -> Plan:
        if mode not in ("paper", "live", "test"):
            raise ValueError("모드는 paper · live · test")
        if await sizing.open_plan_exists(s, symbol):
            raise state.TransitionError("같은 종목에 열린 계획이 이미 있습니다")
        plan = Plan(mode=mode, source=source, symbol=symbol, state=state.DRAFT, revision=1)
        p = dict(params)
        set_params(plan, p)
        if p.get("avg_price") is not None:
            plan.avg_price = float(p["avg_price"])
        s.add(plan)
        await s.flush()
        refresh_hash(plan)
        await self._event(s, plan, "draft", source)
        return plan

    async def update_draft(self, s, plan: Plan, values: dict) -> Plan:
        """DRAFT 만 값 수정 · 값이 바뀌면 판(revision)이 1 늘고 내용 해시가 다시 계산된다."""
        if plan.state not in state.EDITABLE:
            raise state.TransitionError("초안(DRAFT)만 값을 고칠 수 있습니다")
        p = params_of(plan)
        before = approval_values(plan)
        p.update({k: v for k, v in values.items() if k in APPROVAL_KEYS})
        set_params(plan, p)
        if "avg_price" in values:
            plan.avg_price = float(values["avg_price"])
        if approval_values(plan) != before:
            plan.revision += 1
            refresh_hash(plan)
            await self._event(s, plan, "draft_edit", f"revision {plan.revision}")
        return plan

    async def approve(self, s, plan: Plan, *, by: str) -> Plan:
        """DRAFT → APPROVED. 인증 · 확인 코드는 호출 측(API)이 마친다. 실전 · 시험 계획은 Aside 표시를 고를 수 없다."""
        from .pricing import check_caps

        if plan.state != state.DRAFT:
            raise state.TransitionError("초안만 승인할 수 있습니다")
        if plan.mode != "paper" and by != "대표":
            raise state.TransitionError("실전 · 시험 계획은 대표만 승인합니다")
        if by not in ("대표", "Aside(대표 지시)"):
            raise state.TransitionError("승인 주체가 올바르지 않습니다")
        if await sizing.open_plan_exists(s, plan.symbol, plan.id):
            raise state.TransitionError("같은 종목에 열린 계획이 이미 있습니다")
        p = params_of(plan)
        qty = int(p.get("qty") or 0)
        price = D(p.get("buy_order") or p.get("avg_price") or 0)
        if not p.get("adopt") and qty <= 0:
            raise state.TransitionError("수량이 0 입니다 · 예산 또는 매수가를 확인해 주십시오")
        if plan.mode != "paper":
            open_total = await self._open_total_usd(s, plan.id)
            why = check_caps(mode=plan.mode, order_usd=price * qty, open_total_usd=open_total)
            if why:
                raise state.TransitionError(why)
        plan.approved_by, plan.approved_at = by, self.clock()
        await state.transition(s, plan, state.APPROVED, reason=f"approved by {by}")
        return plan

    async def _open_total_usd(self, s, exclude_id: int) -> Decimal:
        rows = await s.scalars(select(Plan).where(Plan.id != exclude_id, Plan.mode != "paper",
                                                  Plan.state.in_(sizing.OPEN_STATES)))
        total = Decimal(0)
        for r in rows:
            p = params_of(r)
            total += D(p.get("buy_order") or p.get("avg_price") or 0) * int(p.get("qty") or r.plan_qty_hint or 0)
        return total

    # ───────────────── 진입 ─────────────────
    async def start_entry(self, s, plan: Plan) -> bool:
        """APPROVED → ENTRY_ARMED (실거래 스위치가 켜져 있고 Kill Switch 가 새 진입을 막지 않을 때만)."""
        if plan.state != state.APPROVED:
            return False
        if not self._live_on(plan):
            await self._once(s, plan, "switch_off_wait", "실거래 꺼짐 · 새 주문 안 냄" if plan.mode != "paper"
                             else "모의 꺼짐 · 새 주문 안 냄")
            return False
        if self.kill_state()[0]:
            await self._once(s, plan, "kill_wait", "Kill Switch 로 새 진입 멈춤")
            return False
        await self._place_buy(s, plan)
        await state.transition(s, plan, state.ENTRY_ARMED)
        return True

    async def _once(self, s, plan: Plan, kind: str, detail: str) -> None:
        last = await s.scalar(select(state.PlanEvent.id).where(
            state.PlanEvent.plan_id == plan.id, state.PlanEvent.kind == kind).limit(1))
        if last is None:
            await self._event(s, plan, kind, detail)

    async def _place_buy(self, s, plan: Plan) -> Optional[PlanLeg]:
        """매수 주문은 계획당 동시에 1개 (5절 8항)."""
        existing = await s.scalar(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status == "WATCHING"))
        if existing:
            return existing
        p = params_of(plan)
        qty = int(p.get("qty") or 0)
        if qty <= 0:
            return None
        watch, order = floor_tick(p["buy_watch"]), floor_tick(p["buy_order"])
        cid = self._cid(plan, "buy", 1)
        expire = p.get("buy_expire") or self._expire(7)
        res = await self.gate.place_buy(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=watch, order=order,
                                        client_id=cid, expire=expire, check=lambda cur: sanity.check_band(watch, cur, "매수 감시"))
        if res.kind == "invalid":
            await self._sanity_reject(s, plan, "매수", res.reason)
            return None
        leg = PlanLeg(plan_id=plan.id, role="buy", seq=1, kind=res.kind if res.kind in ("cond", "limit") else "cond",
                      side="BUY", toss_id=res.id, client_order_id=cid, qty=qty, watch_price=float(watch),
                      order_price=float(order), status="WATCHING", expire_date=expire)
        s.add(leg)
        await s.flush()
        return leg

    async def _cancel_pending_buys(self, s, plan: Plan) -> int:
        """계획 매도를 내기 전에 · 실거래 끌 때 · 마감 처리 때 대기 매수(조건주문 · 일반 주문)를 취소한다."""
        n = 0
        legs = await s.scalars(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status == "WATCHING"))
        for leg in list(legs):
            if leg.toss_id:
                if leg.kind == "limit":
                    await self.gate.cancel_limit(s, leg.toss_id)
                else:
                    await self.gate.cancel_cond(s, leg.toss_id)
            leg.status = "CANCELED"
            n += 1
        await s.flush()
        return n

    async def cancel_buys_on_switch_off(self, s, plan: Plan) -> bool:
        """끄는 즉시 계획 매수 조건주문을 취소 · 실패하면 3초 뒤 1번 더 · 그래도 실패면 ⑨ 긴급 (4-3)."""
        import asyncio

        for attempt in (1, 2):
            try:
                await self._cancel_pending_buys(s, plan)
                return True
            except ExecutionError:
                if attempt == 1:
                    await asyncio.sleep(3)
        await self._alert(plan, "critical", "매수 조건주문 취소 실패", "스위치를 껐지만 토스에 걸린 매수 조건주문을 지우지 못했습니다.")
        return False

    # ───────────────── 체결 읽기 ─────────────────
    async def _record_fill(self, s, plan: Plan, side: str, ref: str, cum_filled: int, avg) -> int:
        """주문 번호별 누적 체결 수량에서 새로 늘어난 만큼만 장부에 더한다 (같은 체결을 두 번 더하지 않음)."""
        have = int(sum([f.qty for f in await s.scalars(
            select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.order_ref == ref))] or [0]))
        delta = int(cum_filled) - have
        if delta <= 0:
            return 0
        s.add(PlanFill(plan_id=plan.id, side=side, qty=delta, price=float(avg or 0), order_ref=ref,
                       fill_seq=int(cum_filled)))
        await s.flush()
        return delta

    async def sync_orders(self, s, plan: Plan) -> dict:
        """토스(또는 모의)에서 다리 · 예약 상태를 읽어 장부에 맞춘다."""
        out = {"buy_filled": 0, "tp1_filled": False, "sold": 0}
        legs = list(await s.scalars(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.status.in_(("WATCHING", "TRIGGERED")))))
        for leg in legs:
            if not leg.toss_id:
                continue
            g = await (self.gate.limit_get(s, leg.toss_id) if leg.kind == "limit" else self.gate.cond_get(s, leg.toss_id))
            if g is None:
                leg.status = "CANCELED"
                await self._event(s, plan, "leg_missing", f"{leg.role}{leg.seq}")
                continue
            st = g.get("status")
            filled = int(g.get("filled") or 0)
            ref = (g.get("order_id") or leg.toss_id)
            if leg.role == "buy":
                if filled:
                    out["buy_filled"] += await self._record_fill(s, plan, "BUY", ref, filled, g.get("avg"))
                if st == "FILLED" or (st == "CANCELED" and filled):
                    leg.status = "FILLED" if st == "FILLED" else "CANCELED"
                elif st in ("CANCELED", "EXPIRED"):
                    leg.status = st
                continue
            # 매도 다리
            if st == "TRIGGERED" or (st == "FILLED") or filled:
                if leg.status == "WATCHING":
                    leg.status = "TRIGGERED"
                    remaining = int(g.get("remaining") or max(leg.qty - filled, 0))
                    await sizing.reserve(s, plan.id, "triggered", remaining + 0, ref)
                    await self._event(s, plan, "leg_triggered", f"{leg.role}{leg.seq}")
                if filled:
                    d = await self._record_fill(s, plan, "SELL", ref, filled, g.get("avg"))
                    out["sold"] += d
                    await self._sync_reservation_qty(s, plan, ref, int(g.get("remaining") or 0), st)
                    if leg.role == "tp1" and st == "FILLED":
                        out["tp1_filled"] = True
                if st == "FILLED":
                    leg.status = "FILLED"
                    await sizing.release(s, plan.id, ref)
            elif st in ("CANCELED", "EXPIRED"):
                leg.status = st
                await self._event(s, plan, "leg_" + st.lower(), f"{leg.role}{leg.seq}")
        # 접수된 지정가 매도(예약)
        resvs = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.active.is_(True),
            PlanSellReservation.kind != "triggered")))
        for r in resvs:
            if not r.order_ref:
                continue
            g = await self.gate.limit_get(s, r.order_ref)
            if g is None:
                r.active = False
                continue
            filled = int(g.get("filled") or 0)
            if filled:
                out["sold"] += await self._record_fill(s, plan, "SELL", r.order_ref, filled, g.get("avg"))
            if g["status"] == "FILLED":
                r.active = False
                if r.kind == "tp1_watch":
                    out["tp1_filled"] = True
            elif g["status"] == "CANCELED":
                r.active = False
            else:
                r.qty = int(g.get("remaining") or r.qty)
        await s.flush()
        return out

    async def _sync_reservation_qty(self, s, plan: Plan, ref: str, remaining: int, st: str) -> None:
        rows = await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.order_ref == ref,
            PlanSellReservation.active.is_(True)))
        for r in rows:
            r.qty = remaining
            if remaining <= 0:
                r.active = False

    # ───────────────── 다리 값 ─────────────────
    def _session(self, now: datetime) -> str:
        return sess.leg_session(now, self.regular_window(now))

    def _values_for(self, plan: Plan, seq: int, session: str, cur: Decimal) -> Values:
        p = params_of(plan)
        if session == "off":
            return sess.emergency_values(cur)
        if plan.state == state.TRAILING:
            return sess.trail_values(plan.avg_price or 0, plan.peak_price or cur)
        pcts = tuple(D(x) for x in p.get("ladder_pcts") or sess.DEFAULT_LADDER_PCTS)
        return sess.ladder_values(plan.avg_price or cur, pcts)[min(seq, len(pcts)) - 1]

    # ───────────────── 다리 등록 · 수정 · 취소 ─────────────────
    async def _cancel_leg(self, s, plan: Plan, leg: PlanLeg) -> None:
        if leg.toss_id and leg.status == "WATCHING":
            await self.gate.cancel_cond(s, leg.toss_id)
        leg.status = "CANCELED"
        await s.flush()

    async def _register_leg(self, s, plan: Plan, seq: int, qty: int, vals: Values, tag: str) -> Optional[PlanLeg]:
        cid = self._cid(plan, "sl", seq)
        try:
            res = await self.gate.place_stop(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=vals.watch,
                                             order=vals.order, client_id=cid, expire=self._expire(),
                                             check=self._stop_check(plan, vals.watch))
        except ExecutionError as exc:
            await self._event(s, plan, "leg_register_fail", f"sl{seq} {exc.__class__.__name__}")
            return None
        if res.kind == "invalid":
            await self._sanity_reject(s, plan, f"손절 다리 {seq}", res.reason)
            return None
        if res.kind == "cond":
            leg = PlanLeg(plan_id=plan.id, role="sl", seq=seq, kind="cond", toss_id=res.id, client_order_id=cid,
                          qty=qty, watch_price=float(vals.watch), order_price=float(vals.order), status="WATCHING",
                          tag=tag, expire_date=self._expire())
            s.add(leg)
            await s.flush()
            self._reset_reject_loops(plan, seq)
            return leg
        if res.kind == "cross":
            await self._sell_cross(s, plan, seq=seq, qty=qty, cur=res.cur, kind="immediate", old_leg=None, tag=tag)
        return None   # unconfirmed · 다음 걸음에 모자람으로 다시 본다

    async def _modify_leg(self, s, plan: Plan, leg: PlanLeg, *, qty: Optional[int] = None,
                          vals: Optional[Values] = None) -> bool:
        """수정(취소 뒤 새로 만들기) · 수정 중 기록을 먼저 쓴다(7-2) · 방향 문(6-1)을 거친다."""
        v = vals or Values(D(leg.watch_price), D(leg.order_price))
        q = int(qty if qty is not None else leg.qty)
        cid = self._cid(plan, "sl", leg.seq)
        pend = PlanLegPending(leg_id=leg.id, plan_id=plan.id, old_toss_id=leg.toss_id, new_watch=float(v.watch),
                              new_order=float(v.order), qty=q, client_order_id=cid)
        s.add(pend)
        await s.flush()
        try:
            res = await self.gate.place_stop(s, plan_id=plan.id, symbol=plan.symbol, qty=q, watch=v.watch,
                                             order=v.order, client_id=cid, expire=self._expire(),
                                             modify_id=leg.toss_id, check=self._stop_check(plan, v.watch))
        except ExecutionError as exc:
            leg.error_count += 1
            await self._event(s, plan, "leg_modify_fail", f"sl{leg.seq} {exc.__class__.__name__} #{leg.error_count}")
            if leg.error_count >= MAX_LEG_ERRORS:
                await self._halt(s, plan, f"다리 sl{leg.seq} 수정 {MAX_LEG_ERRORS}번 실패")
            return False   # 수정 중 기록은 남겨 다시 맞추기가 짝을 잇는다
        await s.delete(pend)
        if res.kind == "invalid":
            await self._sanity_reject(s, plan, f"손절 다리 {leg.seq} 수정", res.reason)
            return False       # 옛 다리는 그대로 둔다
        if res.kind == "cond":
            leg.toss_id, leg.qty = res.id, q
            leg.watch_price, leg.order_price, leg.client_order_id = float(v.watch), float(v.order), cid
            leg.error_count = 0
            self._reset_reject_loops(plan, leg.seq)
            await s.flush()
            return True
        if res.kind == "cross":
            if res.old_gone:
                leg.status = "CANCELED"
            await self._sell_cross(s, plan, seq=leg.seq, qty=q, cur=res.cur, kind="immediate",
                                   old_leg=None if res.old_gone else leg, tag=leg.tag)
            return False
        return False  # unconfirmed · 옛 다리는 그대로 둔다

    def _stop_check(self, plan: Plan, watch):
        """7-6: 사다리 · 비상 · 시간 손절 = 직전가 ±40% · 추적 = 감시가 ≤ 현재가 − 1틱."""
        if plan.state == state.TRAILING:
            return lambda cur: sanity.check_trail(watch, cur)
        return lambda cur: sanity.check_band(watch, cur, "손절 감시")

    async def _sanity_reject(self, s, plan: Plan, what: str, why: str) -> None:
        await self._event(s, plan, "sanity_reject", f"{what}: {why}")
        await self._alert(plan, "warning", "등록 거부 · 값 점검", f"{what} 등록을 거부했습니다. {why}")

    # ───────────────── 6-1 이미 넘은 다리 → 즉시 지정가 매도 ─────────────────
    def _reset_reject_loops(self, plan: Plan, seq: int) -> None:
        p = params_of(plan)
        loops = p.get("reject_loops") or {}
        if str(seq) in loops:
            loops.pop(str(seq))
            p["reject_loops"] = loops
            set_params(plan, p)

    def _bump_reject_loops(self, plan: Plan, seq: int) -> int:
        p = params_of(plan)
        loops = p.get("reject_loops") or {}
        loops[str(seq)] = int(loops.get(str(seq), 0)) + 1
        p["reject_loops"] = loops
        set_params(plan, p)
        return loops[str(seq)]

    async def _sell_cross(self, s, plan: Plan, *, seq: int, qty: int, cur: Decimal, kind: str,
                          old_leg: Optional[PlanLeg], tag: str = "") -> bool:
        """이미 넘은 다리 처리: 대기 매수 취소 → 그 다리를 먼저 줄임 → 바로 지정가 매도 · 예약 장부에 올림."""
        now = self.clock()
        f = self.limit_factor(now)
        if f is None:
            await self._alert(plan, "critical", "지정가를 낼 수 없는 시간대",
                              f"손절 다리 {seq} 가 이미 넘었지만 지금은 지정가를 낼 수 없어 기존 다리를 그대로 둡니다.")
            return False
        await self._cancel_pending_buys(s, plan)
        if old_leg is not None:
            await self._cancel_leg(s, plan, old_leg)       # 다리를 먼저 줄인다 (매도 합 ≤ 보유)
        price = sell_order(D(cur) * f)
        resv = await sizing.reserve(s, plan.id, kind, qty, None)
        resv.leg_seq, resv.order_price = seq, float(price)
        cid = self._cid(plan, "x", seq)
        try:
            oid = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, price=price,
                                             client_id=cid)
        except (OrderRejected, ExecutionError) as exc:
            resv.active = False
            await self._event(s, plan, "sell_rejected", f"sl{seq} {exc.__class__.__name__}")
            await self._after_reject(s, plan, seq=seq, qty=qty, old=old_leg, tag=tag)
            return False
        resv.order_ref = oid
        await self._event(s, plan, "sell_cross", f"sl{seq} qty {qty}")
        return True

    async def _after_reject(self, s, plan: Plan, *, seq: int, qty: int, old: Optional[PlanLeg], tag: str) -> None:
        """매도 거절 → 그 수량의 다리를 「6-1 을 통과하는 값」으로 다시 건다. 같은 다리에서 3번 되풀이되면 HALTED."""
        loops = self._bump_reject_loops(plan, seq)
        if loops >= MAX_REJECT_LOOPS:
            await self._halt(s, plan, f"손절 다리 {seq} 매도 거절 {MAX_REJECT_LOOPS}번 되풀이 · 통과하는 다리만 남김")
            return
        cur = await self.gate.current(s, plan.symbol)
        tried: list[Values] = []
        if old is not None and old.watch_price:
            tried.append(Values(D(old.watch_price), D(old.order_price)))
        emergency_w = ceil_tick(cur * sess.EMERGENCY_FACTOR)
        tried.append(Values(emergency_w, order_price_from_watch(emergency_w, sess.OFFHOURS_FACTOR)))
        for v in tried:
            cid = self._cid(plan, "sl", seq)
            try:
                res = await self.gate.place_stop(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=v.watch,
                                                 order=v.order, client_id=cid, expire=self._expire())
            except ExecutionError:
                continue
            if res.kind == "cond":
                s.add(PlanLeg(plan_id=plan.id, role="sl", seq=seq, kind="cond", toss_id=res.id, client_order_id=cid,
                              qty=qty, watch_price=float(v.watch), order_price=float(v.order), status="WATCHING",
                              tag="emergency", expire_date=self._expire()))
                await s.flush()
                return
        await self._halt(s, plan, f"손절 다리 {seq} 를 다시 걸지 못함")

    # ───────────────── 불변식 · 사다리 ─────────────────
    async def _base_and_accepted(self, s, plan: Plan) -> tuple[int, int, int]:
        pq = await sizing.plan_qty(s, plan)
        acct = await self.gate.account_qty(s, plan.id, plan.symbol)
        acc = await sizing.accepted_sell(s, plan.id)
        if acct < pq:
            await self._event(s, plan, "account_short", f"plan_qty {pq} account {acct}")
        return sizing.compute_base(pq, acct), acc, pq

    async def ensure_ladder(self, s, plan: Plan) -> str:
        """체결 · 전이 · 다시 맞추기 직후 불변식 검사 (5절 10항). 반환: ok | fixed | halted | skipped."""
        if plan.state in (state.DRAFT, state.APPROVED, state.CLOSED, state.CANCELLED, state.ENTRY_ARMED,
                          state.ENTRY_RETRY, state.ADOPT_PENDING):
            return "skipped"
        base, acc, pq = await self._base_and_accepted(s, plan)
        legs = await sizing.live_sl_legs(s, plan.id)
        seqs = [l.seq for l in legs]
        dup = len(seqs) != len(set(seqs))
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in legs], dup_pairs=dup)
        if rep.status == "ok":
            return "ok"
        now = self.clock()
        session = self._session(now)
        cur = await self.gate.current(s, plan.symbol)
        if rep.status == "excess":
            if dup:
                await self._halt(s, plan, "같은 번호의 손절 다리가 둘 이상 (짝이 여럿)")
                return "halted"
            return await self._shrink_sl(s, plan, legs, rep.target)
        # 모자람 · HALTED 에서도 허용 · ⑨ 알림
        if plan.state == state.HALTED and not self._live_on(plan):
            pass  # 보호 다리 다시 걸기는 스위치와 무관하게 허용 (손절을 지우면 위험이 커진다)
        missing = rep.delta
        await self._alert(plan, "warning", "손절 다리 모자람", f"{missing}주분 보호 다리를 다시 겁니다.")
        if not legs:
            seq_qty = list(enumerate(sizing.split_ladder(missing), start=1))
            for seq, q in seq_qty:
                await self._register_leg(s, plan, seq, q, self._values_for(plan, seq, session, cur), tag=session)
        else:
            free = [i for i in (1, 2, 3) if i not in seqs]
            if free:
                await self._register_leg(s, plan, free[0], missing, self._values_for(plan, free[0], session, cur),
                                         tag=session)
            else:
                last = legs[-1]
                await self._modify_leg(s, plan, last, qty=last.qty + missing,
                                       vals=self._values_for(plan, last.seq, session, cur))
        return "fixed"

    async def _shrink_sl(self, s, plan: Plan, legs: list[PlanLeg], target: int) -> str:
        """넘친 다리 축소 (마지막 번호부터) · 정상 넘침(발동 직후)은 바로 줄인다 · 줄이기가 3번 실패하면 HALTED."""
        extra = sum(l.qty for l in legs) - target
        for leg in sorted(legs, key=lambda l: -l.seq):
            if extra <= 0:
                break
            cut = min(leg.qty, extra)
            ok = False
            for _ in range(3):
                try:
                    if cut >= leg.qty:
                        await self._cancel_leg(s, plan, leg)
                    else:
                        ok = await self._modify_leg(s, plan, leg, qty=leg.qty - cut)
                        if not ok:
                            continue
                    ok = True
                    break
                except ExecutionError:
                    continue
            if not ok:
                await self._halt(s, plan, "넘친 손절 다리를 줄이지 못함")
                return "halted"
            extra -= cut
        return "fixed"

    # ───────────────── 상태별 한 걸음 ─────────────────
    async def tick_plan(self, s, plan: Plan, now: Optional[datetime] = None) -> None:
        now = now or self.clock()
        if plan.state in (state.DRAFT, state.CLOSED, state.CANCELLED):
            return
        sw_live = self._live_on(plan)
        killed, sell_allowed = self.kill_state()
        if killed and not sell_allowed and plan.state != state.HALTED and plan.mode != "paper":
            await self._kill_all(s, plan)
            return
        out = await self.sync_orders(s, plan)

        if plan.state == state.APPROVED:
            if plan.source != "adopt":       # 인수 계획은 APPROVED → ADOPT_PENDING 으로 바로 간다 (매수 없음)
                await self.start_entry(s, plan)
            return
        if plan.state in (state.ENTRY_ARMED, state.ENTRY_RETRY):
            await self._tick_entry(s, plan, out, now, sw_live, killed)
            return
        if plan.state == state.ADOPT_PENDING:
            await self._tick_adopt(s, plan, now)
            return
        # 보유 중 상태들
        pq = await sizing.plan_qty(s, plan)
        if out["tp1_filled"] and plan.state == state.HOLDING:
            await self._on_tp1_filled(s, plan)
        if pq <= 0 and not await self._active_reservations(s, plan):
            await self._close(s, plan)
            return
        if plan.state == state.HALTED:
            await self.ensure_ladder(s, plan)     # HALTED 에서도 보호 다리 다시 걸기 · 넘친 다리 축소
            await self._swap_session(s, plan, now)
            return
        await self.ensure_ladder(s, plan)
        if plan.state == state.HALTED:
            return
        await self._swap_session(s, plan, now)
        await self._reprice_stale(s, plan, now)
        if plan.state in (state.HOLDING, state.TP1_WAIT):
            await self._tp1_step(s, plan, sw_live)
        if plan.state in (state.TP1_WAIT, state.TRAILING):
            await self._trail_step(s, plan, now)
        await self._timestop_step(s, plan, now)

    async def _active_reservations(self, s, plan: Plan) -> int:
        return await sizing.accepted_sell(s, plan.id)

    async def _close(self, s, plan: Plan) -> None:
        legs = await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING"))
        for leg in list(legs):
            try:
                if leg.kind == "limit":
                    await self.gate.cancel_limit(s, leg.toss_id)
                else:
                    await self.gate.cancel_cond(s, leg.toss_id)
            except ExecutionError:
                pass
            leg.status = "CANCELED"
        if plan.state != state.CLOSED:
            await state.transition(s, plan, state.CLOSED, reason="plan_qty 0")

    async def _kill_all(self, s, plan: Plan) -> None:
        """Kill Switch 「매도도 멈춤」 · 계획의 모든 조건주문 취소 · HALTED (1절 4항)."""
        legs = await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING"))
        for leg in list(legs):
            try:
                if leg.kind == "limit":
                    await self.gate.cancel_limit(s, leg.toss_id)
                else:
                    await self.gate.cancel_cond(s, leg.toss_id)
                leg.status = "CANCELED"
            except ExecutionError:
                pass
        await self._halt(s, plan, "Kill Switch · 모든 주문 멈춤")

    # ── 진입 ──
    async def _tick_entry(self, s, plan: Plan, out: dict, now: datetime, sw_live: bool, killed: bool) -> None:
        if out["buy_filled"]:
            await self._on_buy_filled(s, plan)
            return
        p = params_of(plan)
        close_at = p.get("entry_close_at")
        buy_leg = await s.scalar(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status == "WATCHING"))
        if killed or not sw_live:
            if buy_leg:
                await self.cancel_buys_on_switch_off(s, plan)
            return
        if plan.state == state.ENTRY_ARMED and close_at and now >= datetime.fromisoformat(str(close_at)):
            await self._cancel_pending_buys(s, plan)           # 마감 처리
            if await sizing.plan_qty(s, plan) > 0:
                await self._on_buy_filled(s, plan)
            else:
                await state.transition(s, plan, state.ENTRY_RETRY, reason="마감 처리")
            return
        if plan.state == state.ENTRY_RETRY:
            end = p.get("entry_window_end")
            if end and now >= datetime.fromisoformat(str(end)):
                await state.transition(s, plan, state.CANCELLED, reason="진입 창 끝")
                return
            reg = self.regular_window(now)
            if buy_leg is None and reg and reg[0] + sess.SWAP_DELAY <= now < reg[1]:
                await self._place_buy(s, plan)                # 정규장 시작 1분 뒤 같은 조건으로 다시 낸다

    async def _on_buy_filled(self, s, plan: Plan) -> None:
        fills = list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "BUY")))
        tot = sum(f.qty for f in fills)
        if tot:
            plan.avg_price = sum(f.qty * f.price for f in fills) / tot
        await state.transition(s, plan, state.HOLDING, reason="매수 체결")
        await self._cancel_pending_buys(s, plan)
        await self.ensure_ladder(s, plan)

    # ── 보유 인수 (8-1) ──
    async def adopt_approve(self, s, plan: Plan) -> None:
        """승인 → ADOPT_PENDING (실거래 스위치가 켜져 있어야 시작)."""
        if not self._live_on(plan):
            raise state.TransitionError("실거래 꺼짐 · 인수를 시작하지 않습니다")
        if self.kill_state()[0] and plan.mode != "paper":
            raise state.TransitionError("Kill Switch 로 새 시작이 멈춰 있습니다")
        p = params_of(plan)
        a = p.get("adopt") or {}
        plan.plan_qty_hint = int(a.get("qty") or 0)
        plan.avg_price = float(a.get("avg_price") or plan.avg_price or 0)
        if a.get("trailing"):
            plan.peak_price = float(a.get("peak") or 0) or None
        await state.transition(s, plan, state.ADOPT_PENDING, reason="인수 승인")

    async def _tick_adopt(self, s, plan: Plan, now: datetime) -> None:
        """10초마다 그 종목의 계획 밖 조건주문(앱에서 건 것)을 본다. 0건이 되는 즉시 다리 등록. 10분 넘으면 ⑨ 1번."""
        foreign = await self._foreign_conds(s, plan)
        if foreign == 0:
            p = params_of(plan)
            a = p.get("adopt") or {}
            await state.transition(s, plan, state.TRAILING if a.get("trailing") else state.HOLDING, reason="인수 완료")
            await self.ensure_ladder(s, plan)
            return
        approved = plan.approved_at or now
        if not plan.adopt_notified and now - approved >= timedelta(minutes=10):
            plan.adopt_notified = True
            await self._alert(plan, "critical", "인수 대기 중", f"앱 조건주문 {foreign}건 남음 · 인수 대기 중")

    async def _foreign_conds(self, s, plan: Plan) -> int:
        own = {l.toss_id for l in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)) if l.toss_id}
        lst = await self.gate.cond_open_list(s, plan.symbol)
        return len([o for o in lst if o and o.get("id") not in own])

    # ── TP1 ──
    async def _tp1_step(self, s, plan: Plan, sw_live: bool) -> None:
        p = params_of(plan)
        if plan.state != state.HOLDING or not p.get("tp1_watch"):
            return
        if await sizing.live_tp1_leg(s, plan.id) is not None:
            return
        # 이미 TP1 감시 모드 예약이 있으면 건드리지 않는다
        if await s.scalar(select(PlanSellReservation.id).where(
                PlanSellReservation.plan_id == plan.id, PlanSellReservation.kind == "tp1_watch",
                PlanSellReservation.active.is_(True))) is not None:
            return
        base, acc, pq = await self._base_and_accepted(s, plan)
        acct = await self.gate.account_qty(s, plan.id, plan.symbol)
        cap = sizing.tp1_cap(base, acc)
        qty = min(cap, int(p.get("tp1_qty") or cap))
        if qty <= 0:
            return
        watch, order = ceil_tick(p["tp1_watch"]), floor_tick(p.get("tp1_order") or p["tp1_watch"])
        why = sanity.check_tp1(watch, plan.avg_price or 0)
        if why:                                  # 7-6: 위반이면 등록 거부 + 알림 (같은 사유로 반복 알리지 않음)
            if not params_of(plan).get("tp1_sanity_alerted"):
                pp = params_of(plan)
                pp["tp1_sanity_alerted"] = True
                set_params(plan, pp)
                await self._sanity_reject(s, plan, "TP1", why)
            return
        if sizing.must_use_tp1_watch(acct, pq) or p.get("tp1_mode") == "watch":
            await self._tp1_watch_mode(s, plan, qty, watch)
            return
        try:
            res = await self.gate.place_tp1(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=watch, order=order,
                                            client_id=self._cid(plan, "tp", 1), expire=self._expire())
        except OrderRejected:
            # U1: 합이 보유를 넘는 등록 거절 → TP1 감시 모드
            await self._tp1_watch_mode(s, plan, qty, watch)
            return
        except ExecutionError:
            return
        if res.kind == "cond":
            s.add(PlanLeg(plan_id=plan.id, role="tp1", seq=1, kind="cond", toss_id=res.id, qty=qty,
                          watch_price=float(watch), order_price=float(order), status="WATCHING",
                          expire_date=self._expire()))
            await s.flush()
        else:
            await self._tp1_watch_mode(s, plan, qty, watch)

    async def _tp1_watch_mode(self, s, plan: Plan, qty: int, watch: Decimal) -> None:
        """TP1 감시 모드: 현재가가 TP1 에 닿으면 · 손절 다리를 먼저 줄인 뒤 · 대기 매수를 취소하고 · 지정가 매도 (7-5)."""
        cur = await self.gate.current(s, plan.symbol)
        if cur < watch:
            return
        f = self.limit_factor(self.clock())
        if f is None:
            return
        await self._cancel_pending_buys(s, plan)
        base, acc, _ = await self._base_and_accepted(s, plan)
        legs = await sizing.live_sl_legs(s, plan.id)
        await self._shrink_sl(s, plan, legs, sizing.sl_target(base, acc + qty))    # 5절 7항: 매도 전에 다리 먼저 축소
        price = sell_order(watch)
        resv = await sizing.reserve(s, plan.id, "tp1_watch", qty, None)
        resv.order_price = float(price)
        try:
            resv.order_ref = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, price=price,
                                                        client_id=self._cid(plan, "tp", 2))
        except (OrderRejected, ExecutionError):
            resv.active = False
            await self.ensure_ladder(s, plan)     # 거절 → 다리 원래대로
            return
        await self._event(s, plan, "tp1_watch_sell", f"qty {qty}")

    async def _on_tp1_filled(self, s, plan: Plan) -> None:
        """TP1 체결 → 추적 감시가 = max(평단, 정규장 고점 × 0.85) · 감시가 ≤ 현재가 − 1틱이면 추적 전환 · 아니면 익절 뒤 대기 (7-3)."""
        cur = await self.gate.current(s, plan.symbol)
        peak = plan.peak_price or float(cur)
        v = sess.trail_values(plan.avg_price or 0, peak)
        from .pricing import below_by_tick

        if below_by_tick(v.watch, cur):
            await state.transition(s, plan, state.TRAILING, reason="TP1 체결 · 추적 전환")
            await self._convert_to_trail(s, plan, v)
        else:
            await state.transition(s, plan, state.TP1_WAIT, reason="TP1 체결 · 익절 뒤 대기")
            await self.ensure_ladder(s, plan)    # 손절 다리 3건 수량만 불변식 A 로 줄임

    async def _convert_to_trail(self, s, plan: Plan, v: Values) -> None:
        """추적 손절도 3건 유지: 남은 수량을 불변식 A 로 3건에 나눈 뒤 3건의 값을 하나씩 차례로 수정 (한 건 수정 중 다른 2건은 걸려 있음)."""
        base, acc, _ = await self._base_and_accepted(s, plan)
        target = sizing.sl_target(base, acc)
        want = sizing.split_ladder(target)
        legs = await sizing.live_sl_legs(s, plan.id)
        for i, leg in enumerate(legs):
            q = want[i] if i < len(want) else 0
            if q <= 0:
                await self._cancel_leg(s, plan, leg)
                continue
            await self._modify_leg(s, plan, leg, qty=q, vals=v)
        await self.ensure_ladder(s, plan)

    async def _trail_step(self, s, plan: Plan, now: datetime) -> None:
        """추적 상향: 위로만 · 최소 폭 $0.005 또는 감시가의 0.5% 중 큰 값 (7-3)."""
        from .pricing import below_by_tick

        cur = await self.gate.current(s, plan.symbol)
        # 고점은 정규장 체결가로만 (장외 · 특수 체결 제외) · 정규장 밖이면 갱신하지 않는다
        reg = self.regular_window(now)
        if reg and reg[0] <= now < reg[1]:
            plan.peak_price, plan.pending_peak = sess.update_peak(plan.peak_price, plan.pending_peak, float(cur))
        v = sess.trail_values(plan.avg_price or 0, plan.peak_price or cur)
        if plan.state == state.TP1_WAIT:
            if below_by_tick(v.watch, cur):
                await state.transition(s, plan, state.TRAILING, reason="추적 전환")
                await self._convert_to_trail(s, plan, v)
            return
        legs = await sizing.live_sl_legs(s, plan.id)
        if not legs or self._session(now) == "off":
            return
        old = D(legs[0].watch_price)
        vv = Values(min(v.watch, sess.cap_sell_watch(v.watch, cur)), v.order)
        if vv.watch > old and sess.trail_should_raise(old, vv.watch):
            for leg in legs:
                await self._modify_leg(s, plan, leg, vals=vv)    # 3건 하나씩 차례로

    # ── 세션 교대 ──
    async def _swap_session(self, s, plan: Plan, now: datetime) -> None:
        """시간대가 바뀌면 같은 3건을 수정한다 (정규장 사다리 ↔ 정규장 밖 비상 손절)."""
        if plan.state in (state.ENTRY_ARMED, state.ENTRY_RETRY, state.ADOPT_PENDING):
            return
        session = self._session(now)
        legs = await sizing.live_sl_legs(s, plan.id)
        if not legs:
            return
        cur = await self.gate.current(s, plan.symbol)
        for leg in legs:
            if leg.tag == session:
                continue
            if plan.state == state.TRAILING and session == "regular":
                v = sess.trail_values(plan.avg_price or 0, plan.peak_price or cur)
            else:
                v = self._values_for(plan, leg.seq, session, cur)
            if await self._modify_leg(s, plan, leg, vals=v):
                leg.tag = session

    # ── 접수된 매도가 안 팔릴 때 10초 다시 내기 (7-4 · 7-5) ──
    async def _reprice_stale(self, s, plan: Plan, now: datetime) -> None:
        rows = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.active.is_(True),
            PlanSellReservation.kind.in_(("time_stop", "tp1_watch", "immediate")),
            PlanSellReservation.order_ref.is_not(None))))
        if not rows:
            return
        cur = await self.gate.current(s, plan.symbol)
        p = params_of(plan)
        for r in rows:
            threshold = D(r.order_price or 0)
            if r.kind == "tp1_watch":
                threshold = D(p.get("tp1_watch") or 0) * Decimal("0.99")
            if D(cur) >= threshold:
                r.below_since = None
                continue
            if r.below_since is None:
                r.below_since = now
                continue
            if (now - r.below_since).total_seconds() < REPRICE_AFTER_SEC:
                continue
            await self._cancel_and_reprice(s, plan, r, cur)

    async def _cancel_and_reprice(self, s, plan: Plan, r: PlanSellReservation, cur: Decimal) -> None:
        try:
            await self.gate.cancel_limit(s, r.order_ref)
        except ExecutionError:
            return
        g = await self.gate.limit_get(s, r.order_ref) or {}
        filled = int(g.get("filled") or 0)
        if filled:
            await self._record_fill(s, plan, "SELL", r.order_ref, filled, g.get("avg"))
        remaining = int(g.get("remaining") if g.get("remaining") is not None else r.qty - filled)
        r.active = False
        r.below_since = None
        if remaining <= 0:
            return
        if r.kind == "tp1_watch":
            await self.ensure_ladder(s, plan)      # 다리 수량 되돌림 (손절 없는 수량이 남는 시간을 10초로 줄임)
            return
        if r.retries >= 1:                         # 다시 내기가 2번 실패 → 예약을 풀고 보호 다리를 다시 건 뒤 ⑨ 긴급
            await self.ensure_ladder(s, plan)
            await self._alert(plan, "critical", "다시 내기 실패", f"{remaining}주 매도를 다시 내지 못해 보호 다리를 다시 겁니다.")
            return
        price = sell_order(D(cur) * Decimal("0.95"))
        new = await sizing.reserve(s, plan.id, r.kind, remaining, None)
        new.leg_seq, new.order_price, new.retries = r.leg_seq, float(price), r.retries + 1
        try:
            new.order_ref = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=remaining,
                                                       price=price, client_id=self._cid(plan, "x", r.leg_seq or 0))
        except (OrderRejected, ExecutionError):
            new.active = False
            await self.ensure_ladder(s, plan)
            await self._alert(plan, "critical", "다시 내기 실패", f"{remaining}주 매도를 다시 내지 못해 보호 다리를 다시 겁니다.")

    # ── 시간 손절 (7-4) ──
    async def _timestop_step(self, s, plan: Plan, now: datetime) -> None:
        p = params_of(plan)
        if plan.state != state.HOLDING or not p.get("announce_at"):
            return
        if plan.timestop_stage == "stopped":
            return
        reg = self.regular_window(now)
        if not reg or not (reg[0] <= now < reg[1]):
            return
        if not sess.timestop_due(datetime.fromisoformat(str(p["announce_at"])), now, self.holidays()):
            return
        w = sess.timestop_window(reg)
        today = now.strftime("%Y-%m-%d")
        cur = await self.gate.current(s, plan.symbol)
        legs = await sizing.live_sl_legs(s, plan.id)
        if plan.timestop_stage in ("none", "lift") and plan.timestop_lift_session in (None, today) \
                and w.lift_from <= now < w.clean_from:
            last = p.get("lift_last")
            if last and (now - datetime.fromisoformat(str(last))).total_seconds() < 15 * 60:
                return                                   # 15분마다 같은 계산으로 위로만 다시 수정
            plan.timestop_stage, plan.timestop_lift_session = "lift", today
            p["lift_last"] = now.isoformat()
            set_params(plan, p)
            v = sess.lift_values(cur)
            for leg in legs:
                if v.watch > D(leg.watch_price):
                    await self._modify_leg(s, plan, leg, vals=v)
            return
        if now >= w.clean_from and now < w.cancel_at:
            plan.timestop_stage = "clean"
            for leg in legs:           # 1건씩 · 접수된 뒤 다음 건 (이미 넘은 다리 처리와 같다)
                if await self._sell_cross(s, plan, seq=leg.seq, qty=leg.qty, cur=cur, kind="time_stop", old_leg=leg,
                                          tag=leg.tag):
                    break
            return
        if now >= w.cancel_at:         # 종료 1분 전: 체결 안 된 매도 취소 · 비상 손절 값의 다리로 되돌림
            rows = await s.scalars(select(PlanSellReservation).where(
                PlanSellReservation.plan_id == plan.id, PlanSellReservation.kind == "time_stop",
                PlanSellReservation.active.is_(True)))
            for r in list(rows):
                try:
                    await self.gate.cancel_limit(s, r.order_ref)
                    r.active = False
                except ExecutionError:
                    pass
            await self.ensure_ladder(s, plan)

    async def stop_timestop(self, s, plan: Plan) -> None:
        """대표가 「시간 손절 중지」 → 끌어올리기 · 정리를 멈추고 남은 다리를 시간대 값으로 되돌린다 (위험 줄이는 동작)."""
        plan.timestop_stage = "stopped"
        now = self.clock()
        cur = await self.gate.current(s, plan.symbol)
        session = self._session(now)
        for leg in await sizing.live_sl_legs(s, plan.id):
            await self._modify_leg(s, plan, leg, vals=self._values_for(plan, leg.seq, session, cur))
        await self._event(s, plan, "timestop_stopped", "")

    # ── 계획 정지 · 재개 ──
    async def stop_plan(self, s, plan: Plan, reason: str = "계획 정지") -> None:
        """새 등록 · 매수를 멈추고 대기 매수를 취소한다. 매도 다리는 지우지 않는다 (3절)."""
        await self._cancel_pending_buys(s, plan)
        await state.halt(s, plan, reason)

    async def resume_plan(self, s, plan: Plan) -> str:
        """HALTED → 이전 상태. 다시 맞춘 뒤 불변식이 통과해야 한다."""
        await self.ensure_ladder(s, plan)
        if plan.state != state.HALTED:
            raise state.TransitionError("다시 맞추는 중 다시 정지되었습니다")
        base, acc, _ = await self._base_and_accepted(s, plan)
        legs = await sizing.live_sl_legs(s, plan.id)
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in legs])
        if rep.status != "ok":
            raise state.TransitionError("불변식을 통과하지 못해 재개할 수 없습니다")
        return await state.resume(s, plan)
