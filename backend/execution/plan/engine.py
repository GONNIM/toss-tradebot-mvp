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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from backend.execution.exceptions import ExecutionError, OrderRejected

from . import orderbook as ob
from . import sanity
from . import sessions as sess
from . import sizing, state
from .brokers import DirectionGate, GateResult
from .models import Plan, PlanFill, PlanLeg, PlanSellReservation, utcnow
from .pricing import D, ceil_tick, floor_tick, order_price_from_watch, qty_for_budget, sell_order
from .sessions import Values
from .switches import content_hash_of

logger = logging.getLogger(__name__)

# 보유 전 단계 (정지돼도 보호 다리 · 닫기 · 인수 대신 다리 걸기를 하지 않는다)
PRE_HOLD_STATES = (state.APPROVED, state.ENTRY_ARMED, state.ENTRY_RETRY, state.ADOPT_PENDING)

SELL_EXPIRE_DAYS = 90            # 매도 다리 만료 = 등록일 + 90일 (6-1)
EXPIRE_EXTEND_BELOW_DAYS = 10    # 남은 기간이 10일 아래면 같은 값으로 수정해 연장
MAX_REJECT_LOOPS = 3             # 같은 다리 거절 · 다시 걸기 3번 → HALTED (6-1)
MAX_LEG_ERRORS = 3               # 같은 다리 오류 3번 → HALTED (9절)
REPRICE_AFTER_SEC = 10           # 접수된 매도가 주문가 아래로 내려가면 10초 안에 다시 내기 (7-4)

Notify = Callable[[str, str, str, str], Awaitable[Any]]   # (level, title, body, category)


def parse_dt(raw) -> datetime:
    """`YYYY-MM-DDTHH:mm:00+09:00` 같은 시간대 있는 값도 · 시간대 없는 값도 받아 엔진 시계(UTC · 시간대 없음)로 맞춘다."""
    d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def runtime_of(plan: Plan) -> dict:
    """실행기가 남긴 마지막 값 · 별도 칸(runtime_json) · 승인 대상 값이 아니라 내용 해시에 들어가지 않는다."""
    try:
        r = json.loads(plan.runtime_json or "{}")
    except ValueError:
        return {}
    return r if isinstance(r, dict) else {}


def set_runtime(plan: Plan, **kv) -> None:
    r = runtime_of(plan)
    r.update(kv)
    plan.runtime_json = json.dumps(r, ensure_ascii=False, default=str)


def params_of(plan: Plan) -> dict:
    try:
        return json.loads(plan.params_json or "{}")
    except ValueError:
        return {}


def set_params(plan: Plan, p: dict) -> None:
    plan.params_json = json.dumps(p, ensure_ascii=False, default=str)


APPROVAL_KEYS = ("symbol", "mode", "budget_usd", "buy_watch", "buy_order", "qty", "tp1_watch", "tp1_order",
                 "ladder_pcts", "announce_at", "entry_close_at", "entry_window_end", "adopt")


# 계획을 만들 때 받는 값 (그 밖의 키는 버린다)
PARAM_ALLOWED = set(APPROVAL_KEYS) | {"avg_price", "buy_expire", "tp1_qty", "tp1_mode", "rationale", "warnings", "user_edited"}

# 자동 초안에서 대표가 바꿀 수 있는 값 (v4 7절 · 바꾸면 「사용자 수정」 표시 · 매일 다시 계산해도 유지)
USER_EDITABLE_KEYS = ("budget_usd", "buy_watch", "buy_order", "qty", "tp1_watch", "tp1_order", "ladder_pcts")


def approval_values(plan: Plan) -> dict:
    p = params_of(plan)
    v = {k: p.get(k) for k in APPROVAL_KEYS if k in p}
    v["symbol"], v["mode"] = plan.symbol, plan.mode
    return v


def refresh_hash(plan: Plan) -> None:
    plan.content_hash = content_hash_of(approval_values(plan))


def derive_qty(params: dict) -> Optional[int]:
    """수량을 정하는 서버 한 곳 (계획서 6절): 예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림 (pricing.qty_for_budget).
    예산 · 매수가가 없으면 계산할 수 없어 None (이때만 받은 수량을 그대로 둔다). 보유 인수 계획은 인수 수량을 쓰므로 None."""
    if params.get("adopt"):
        return None
    budget = params.get("budget_usd")
    price = params.get("buy_order") if params.get("buy_order") is not None else params.get("buy_watch")
    try:
        b, px = float(budget), float(price)
    except (TypeError, ValueError):
        return None
    return qty_for_budget(b, floor_tick(px))


definitely_not_created = ob.definitely_not_created      # 판정은 장부 모듈 한 곳 (같은 함수)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
            from backend.services import alert_text as at
            from backend.services.stock_names import peek_name

            # 1119-02 · 종목 줄은 기억된 회사명만 쓴다 (새 조회를 기다리지 않음 · 없으면 티커만) · 제목에는 이름을 넣지 않는다
            who = f"종목 {at.us_stock(plan.symbol, peek_name(plan.symbol))}"
            if plan.mode == "paper":
                await self._notify(level, f"[모의 시험] {title}", f"[모의 시험] 계획 번호 {plan.id}\n{who}\n{body}", "system")
            else:
                await self._notify(level, title, f"계획 번호 {plan.id}\n{who}\n{body}", "execution")
        except Exception as exc:  # noqa: BLE001 — 알림 실패가 주문 흐름을 막지 않는다
            logger.warning("[plan] 알림 실패 · %s", exc.__class__.__name__)

    async def _event(self, s, plan: Plan, kind: str, detail: str = "") -> None:
        await state.event(s, plan.id, kind, detail)

    async def _halt(self, s, plan: Plan, reason: str, *, urgent: bool = True) -> None:
        if await state.halt(s, plan, reason):
            if urgent:
                await self._alert(plan, "critical", "계획 정지", reason)

    def _cid(self, plan: Plan, role: str, seq: int) -> str:
        """주문 고유 키는 「다리 + 판」 단위로 고정한다. 같은 판을 다시 낼 때(불확실한 실패 뒤) 같은 키를 쓰고,
        성공하거나 확실히 거절된 뒤에만 판이 올라간다 (_bump_cid)."""
        ver = int((runtime_of(plan).get("cid_ver") or {}).get(f"{role}{seq}", 1))
        return f"{plan.id}-{role}{seq}-v{ver}"[:36]

    @staticmethod
    def _cid_key(leg: PlanLeg) -> tuple[str, int]:
        return ("tp", 1) if leg.role == "tp1" else (leg.role, leg.seq)

    def _bump_leg_cid(self, plan: Plan, leg: PlanLeg) -> None:
        role, seq = self._cid_key(leg)
        self._bump_cid(plan, role, seq)

    def _bump_cid(self, plan: Plan, role: str, seq: int) -> None:
        rt = runtime_of(plan)
        vers = dict(rt.get("cid_ver") or {})
        vers[f"{role}{seq}"] = int(vers.get(f"{role}{seq}", 1)) + 1
        set_runtime(plan, cid_ver=vers)

    def _sell_stopped(self, plan: Plan) -> bool:
        """Kill Switch 「매도도 멈춤」 · 이때는 어떤 경로로도 등록 · 수정 · 매도를 내지 않는다 (실거래 계획만)."""
        killed, sell_allowed = self.kill_state()
        return bool(killed and not sell_allowed and plan.mode != "paper")

    async def _alert_once(self, s, plan: Plan, key: str, level: str, title: str, body: str, every_sec: int = 3600) -> None:
        """같은 경고를 every_sec 안에 두 번 보내지 않는다 (실행기 값 칸에 마지막 시각을 남김)."""
        rt = runtime_of(plan)
        last = (rt.get("alert_at") or {}).get(key)
        now = self.clock()
        if last and (now - parse_dt(last)).total_seconds() < every_sec:
            return
        at = dict(rt.get("alert_at") or {})
        at[key] = now.isoformat()
        set_runtime(plan, alert_at=at)
        await self._alert(plan, level, title, body)

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
        p = {k: v for k, v in params.items() if k in PARAM_ALLOWED}      # 허용 목록 밖 키는 버린다 (실행기 내부 값 덮어쓰기 막음)
        q = derive_qty(p)
        if q is not None:
            p["qty"] = q                      # 화면이 보낸 qty 와 달라도 서버 계산값을 쓴다
        set_params(plan, p)
        if p.get("avg_price") is not None:
            plan.avg_price = float(p["avg_price"])
        s.add(plan)
        await s.flush()
        refresh_hash(plan)
        await self._event(s, plan, "draft", source)
        return plan

    async def update_draft(self, s, plan: Plan, values: dict, *, by_user: bool = True) -> Plan:
        """DRAFT 만 값 수정 · 값이 바뀌면 판(revision)이 1 늘고 내용 해시가 다시 계산된다.

        by_user=True 이면 대표가 바꾼 값(예산 · 매수가 · TP1 · 손절 폭)을 「사용자 수정」으로 표시한다 (v4 7절).
        """
        if plan.state not in state.EDITABLE:
            # 「발표 시각 입력」 은 승인 뒤에도 가능 (시간 손절 기준 · v4 8절) · 다른 값은 DRAFT 만
            if not (set(values) <= {"announce_at"} and plan.state not in state.TERMINAL):
                raise state.TransitionError("초안(DRAFT)만 값을 고칠 수 있습니다")
        p = params_of(plan)
        before = approval_values(plan)
        if by_user:
            edited = set(p.get("user_edited") or [])
            for k in USER_EDITABLE_KEYS:
                if k in values and values[k] != p.get(k):
                    edited.add(k)
            if edited:
                p["user_edited"] = sorted(edited)
        p.update({k: v for k, v in values.items() if k in APPROVAL_KEYS})
        q = derive_qty(p)
        if q is not None:
            p["qty"] = q
        set_params(plan, p)
        if "avg_price" in values:
            plan.avg_price = float(values["avg_price"])
        if approval_values(plan) != before:
            plan.revision += 1
            refresh_hash(plan)
            await self._event(s, plan, "draft_edit", f"revision {plan.revision}")
        return plan

    async def approval_block_reason(self, s, plan: Plan) -> Optional[str]:
        """승인이 거부하는 값 · 상태 까닭을 한 곳에 모은 검사 (통과면 None · 1116-01 S1~S3).
        코드 확인 앞(`/confirm/challenge` · 승인 API)과 `approve()` 안에서 같은 함수를 부른다 — 값이 틀리면 확인 코드를 쓰지 않는다."""
        from .pricing import check_caps

        if plan.state != state.DRAFT:
            return "초안만 승인할 수 있습니다"
        if await sizing.open_plan_exists(s, plan.symbol, plan.id):
            return "같은 종목에 열린 계획이 이미 있습니다"
        p = params_of(plan)
        adopt = p.get("adopt")
        qty = int(_num(p.get("qty")) or 0)
        if adopt:        # 보유 맡기기: 맡길 수량이 0 이하면 거부 (S2)
            if int(_num((adopt or {}).get("qty") if isinstance(adopt, dict) else None) or 0) <= 0:
                return "맡길 수량이 0 입니다 · 보유 수량을 확인해 주십시오"
        else:
            if qty <= 0:
                return "수량이 0 입니다 · 예산 또는 매수가를 확인해 주십시오"
            if not ((_num(p.get("buy_watch")) or 0) > 0 and (_num(p.get("buy_order")) or 0) > 0):     # S1 · 모의 포함
                return "매수 감시가 · 매수 주문가가 비어 있습니다 · 두 값을 모두 넣어 주십시오"
        price = D(p.get("buy_order") or p.get("avg_price") or 0)
        if plan.mode != "paper":
            open_total = await self._open_total_usd(s, plan.id)
            why = check_caps(mode=plan.mode, order_usd=price * qty, open_total_usd=open_total)
            if why:
                return why
        return None

    async def approve(self, s, plan: Plan, *, by: str) -> Plan:
        """DRAFT → APPROVED. 인증 · 확인 코드는 호출 측(API)이 마친다. 실전 · 시험 계획은 Aside 표시를 고를 수 없다."""
        if plan.state != state.DRAFT:
            raise state.TransitionError("초안만 승인할 수 있습니다")
        if plan.mode != "paper" and by != "대표":
            raise state.TransitionError("실전 · 시험 계획은 대표만 승인합니다")
        if by not in ("대표", "Aside(대표 지시)"):
            raise state.TransitionError("승인 주체가 올바르지 않습니다")
        why = await self.approval_block_reason(s, plan)        # 코드 확인 앞에서 부르는 같은 검사 (1116-01 S1~S3)
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
        """매수 주문은 계획당 동시에 1개 (5절 8항). 낸 결과를 모르면 「확인 대기」 로 두고 장부 대조(ob.reconcile)가 판정한다."""
        existing = await s.scalar(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status.in_(("WATCHING", "UNCERTAIN"))))
        if existing:
            return existing                    # 결과를 모르는 매수가 있으면(UNCERTAIN) 다시 사지 않는다
        p = params_of(plan)
        qty = int(p.get("qty") or 0)
        if qty <= 0:
            return None
        watch, order = floor_tick(p["buy_watch"]), floor_tick(p["buy_order"])
        cid = self._cid(plan, "buy", 1)
        expire = p.get("buy_expire") or self._expire(7)
        try:
            acct_before = int(await self.gate.account_qty(s, plan.id, plan.symbol))   # 경보에만 쓴다 (체결 근거 아님)
        except ExecutionError:
            acct_before = None
        leg = PlanLeg(plan_id=plan.id, role="buy", seq=1, kind="cond", side="BUY", client_order_id=cid, qty=qty,
                      watch_price=float(watch), order_price=float(order), status="UNCERTAIN", expire_date=expire)
        s.add(leg)
        await s.flush()
        line = await ob.send(s, plan, cid=cid, kind="cond", role="buy", side="BUY", qty=qty, price=order, watch=watch,
                             leg=leg, acct_before=acct_before, now=self.clock())
        self._bump_cid(plan, "buy", 1)         # 보낼 때마다 새 키
        await s.commit()                       # 토스를 부르기 전에 기록을 남긴다
        try:
            res = await self.gate.place_buy(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=watch, order=order,
                                            client_id=cid, expire=expire,
                                            check=lambda cur: sanity.check_band(watch, cur, "매수 감시"))
        except ExecutionError as exc:
            return await self._after_register_failure(s, plan, leg, "buy", 1, exc, line)
        if res.kind == "invalid":
            ob.mark_not_created(line)
            await s.delete(leg)
            await s.commit()
            await self._sanity_reject(s, plan, "매수", res.reason)
            return None
        leg.kind = res.kind if res.kind in ("cond", "limit") else "cond"
        leg.toss_id, leg.status = res.id, "WATCHING"
        line.kind = leg.kind
        ob.mark_open(line, res.id)
        await s.commit()
        return leg

    async def _after_register_failure(self, s, plan: Plan, leg: PlanLeg, role: str, seq: int, exc: Exception, line=None):
        """등록 실패 처리는 장부 모듈이 판정한다 (거절이면 지움 · 모르면 확인 대기)."""
        return await ob.after_send_failure(s, self, plan, leg, role, seq, exc, line)

    async def _final_read_leg(self, s, plan: Plan, leg: PlanLeg) -> Optional[dict]:
        """취소 전 · 후에 그 다리의 마지막 체결을 다시 읽어 장부에 더한다 (5절 10항).
        빈 조회는 「체결 없음」 이 아니라 모름이라 장부 대조 모듈(on_missing)로 보내고 None 을 돌려준다. 읽기 오류도 None."""
        if not leg.toss_id:
            return None
        try:
            g = await (self.gate.limit_get(s, leg.toss_id) if leg.kind == "limit" else self.gate.cond_get(s, leg.toss_id))
        except ExecutionError:
            return None
        if g is None:
            await ob.on_missing(s, self, plan, leg)
            return None
        filled = int(g.get("filled") or 0)
        if filled:
            side = "BUY" if leg.role == "buy" else "SELL"
            await self._record_fill(s, plan, side, leg.toss_id, filled, g.get("avg"))
        return g

    async def _cancel_leg_orders(self, s, plan: Plan, leg: PlanLeg) -> None:
        """다리 하나를 토스에서 지운다. 읽기 → 취소 → 읽기. 조건이 이미 닿아 자식 주문이 생겼으면 자식 주문(cancel_limit)을 취소한다.
        첫 읽기가 비어도 아는 번호로 취소는 반드시 부른다."""
        g = await self._final_read_leg(s, plan, leg)
        child = g.get("order_id") if (g is not None and leg.kind != "limit") else None
        if child and g.get("status") == "TRIGGERED":
            await self.gate.cancel_limit(s, child)
        elif leg.kind == "limit":
            await self.gate.cancel_limit(s, leg.toss_id)
        else:
            await self.gate.cancel_cond(s, leg.toss_id)
        await self._final_read_leg(s, plan, leg)            # 취소 도중 부분 체결이 있었는지

    async def _cancel_leg_keep_unknown(self, s, plan: Plan, leg: PlanLeg) -> bool:
        """알고 있는 주문 번호는 취소한다. 결과 모르는 줄이 있으면 상태를 CANCELED 로 확정하지 않고
        「새 주문이 있을 수 있음」 ⑨ 긴급 알림을 보낸다. 반환: 닫았는가(True) / 모름이 남았는가(False). 취소 오류는 그대로 올린다."""
        unknown = leg.status == "UNCERTAIN" or await ob.has_unresolved_for_leg(s, leg.id)
        known = bool(leg.toss_id) and not (leg.client_order_id or "").startswith("missing-")
        if leg.toss_id:
            await self._cancel_leg_orders(s, plan, leg)
        if not unknown:
            if leg.status in ("WATCHING", "TRIGGERED"):      # 취소 도중 대조가 FILLED 등으로 닫았으면 덮어쓰지 않는다
                leg.status = "CANCELED"
            return True
        if known and leg.role != "buy" and leg.status != "UNCERTAIN":
            leg.status = "CANCELED"                          # 알던 옛 번호는 지웠다 · 모르는 새 줄은 장부가 묶는다
        await self._alert_once(s, plan, f"unknown_new:{leg.id}", "critical", "새 주문이 있을 수 있음",
                               f"{leg.role}{leg.seq} 주문의 결과를 모릅니다. 아는 번호는 취소했지만 새 주문이 토스에 남아 있을 수 있습니다. 토스 앱에서 확인해 주십시오.",
                               every_sec=ob.REPEAT_ALERT_SEC)
        return False

    async def _cancel_resv(self, s, plan: Plan, r: PlanSellReservation) -> Optional[dict]:
        """접수된 지정가 매도 취소: 읽기 → 취소 → 읽기. 첫 읽기가 비어도 아는 번호(r.order_ref)로 취소는 반드시 부른다.
        빈 조회는 체결 0 이 아니라 모름이라 체결 수량 판정만 대조 모듈(on_missing_reservation)로 보낸다(None · 예약 유지 · 다시 팔지 않음)."""
        before = await self.gate.limit_get(s, r.order_ref)
        if before is not None and int(before.get("filled") or 0):
            await self._record_fill(s, plan, "SELL", r.order_ref, int(before["filled"]), before.get("avg"))
        await self.gate.cancel_limit(s, r.order_ref)
        after = await self.gate.limit_get(s, r.order_ref)
        if before is None or after is None:
            await ob.on_missing_reservation(s, self, plan, r)
            return None
        if int(after.get("filled") or 0):
            await self._record_fill(s, plan, "SELL", r.order_ref, int(after["filled"]), after.get("avg"))
        return after

    async def _cancel_pending_buys(self, s, plan: Plan) -> int:
        """계획 매도를 내기 전에 · 실거래 끌 때 · 마감 처리 때 대기 매수(조건주문 · 일반 주문)를 취소한다."""
        n = 0
        await ob.reconcile(s, self, plan, self.clock())         # 낸 결과를 모르는 매수가 있으면 먼저 대조한다
        legs = await s.scalars(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status.in_(("WATCHING", "UNCERTAIN"))))
        for leg in list(legs):
            if await self._cancel_leg_keep_unknown(s, plan, leg):      # 모름이 남으면 CANCELED 로 두지 않는다 (대조가 판정 · 다시 사지 않음)
                n += 1
        await s.flush()
        return n

    async def cancel_buys_on_switch_off(self, s, plan: Plan) -> bool:
        """끄는 즉시 계획 매수 조건주문을 취소 · 실패하면 3초 뒤 1번 더 · 그래도 실패면 ⑨ 긴급 (4-3)."""
        import asyncio

        for attempt in (1, 2):
            try:
                if await self._cancel_pending_buys(s, plan):
                    set_runtime(plan, rearm_buy=True)         # 다시 켜지면 한 번 다시 건다
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

    async def _acct_now(self, s, plan: Plan) -> Optional[int]:
        try:
            return int(await self.gate.account_qty(s, plan.id, plan.symbol))
        except ExecutionError:
            return None

    async def sync_orders(self, s, plan: Plan) -> dict:
        """토스(또는 모의)에서 다리 · 예약 상태를 읽어 장부에 맞춘다."""
        out = {"buy_filled": 0, "tp1_filled": False, "sold": 0}
        await ob.reconcile(s, self, plan, self.clock())    # 결과 모르는 주문(다리 · 예약 · 수정)은 장부 대조 한 곳에서 판정
        if runtime_of(plan).get("tp1_filled_human"):       # 사람이 TP1 체결을 확정했다 → 추적 전환을 탄다 (표시는 _on_tp1_filled 가 돈 뒤에만 지움)
            out["tp1_filled"] = True
        legs = list(await s.scalars(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.status.in_(("WATCHING", "TRIGGERED")))))
        for leg in legs:
            if not leg.toss_id:
                continue
            g = await (self.gate.limit_get(s, leg.toss_id) if leg.kind == "limit" else self.gate.cond_get(s, leg.toss_id))
            if g is None:
                await ob.on_missing(s, self, plan, leg)    # 바로 CANCELED 로 두지 않는다 (목록 확인 → 사람 확인)
                continue
            ob.clear_miss(plan, f"l{leg.id}")
            st = g.get("status")
            filled = int(g.get("filled") or 0)
            if st == "FILLED" and not filled:
                filled = int(leg.qty)                      # 전량 체결인데 체결 수량 칸이 없으면 다리 수량으로 본다 (확인 못 함 · 응답 모양 미확인)
                g = {**g, "filled": filled, "avg": g.get("avg") or leg.order_price}
            ref = leg.toss_id                              # 체결 장부 열쇠는 다리 번호로 고정 (조건 → 자식 주문으로 바뀌어도 같은 열쇠)
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
                elif leg.status == "TRIGGERED":
                    await ob.check_child(s, self, plan, leg, g, ref, out)
            elif st in ("CANCELED", "EXPIRED", "REJECTED", "UNKNOWN"):
                if leg.status == "TRIGGERED":
                    await ob.check_child(s, self, plan, leg, g, ref, out)
                elif st != "UNKNOWN":
                    leg.status = st if st in ("CANCELED", "EXPIRED") else "CANCELED"
                    await self._event(s, plan, "leg_" + leg.status.lower(), f"{leg.role}{leg.seq}")
        await self._sync_reservations(s, plan, out)
        await s.flush()
        return out

    async def _sync_reservations(self, s, plan: Plan, out: dict) -> None:
        resvs = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.active.is_(True),
            PlanSellReservation.kind != "triggered")))
        for r in resvs:
            if not r.order_ref:
                continue
            g = await self.gate.limit_get(s, r.order_ref)
            if g is None:
                await ob.on_missing_reservation(s, self, plan, r)    # 조회가 비면 목록 확인 → 사람 확인 (예약은 유지)
                continue
            ob.clear_miss(plan, f"r{r.id}")
            filled = int(g.get("filled") or 0)
            if filled:
                out["sold"] += await self._record_fill(s, plan, "SELL", r.order_ref, filled, g.get("avg"))
            if g["status"] == "FILLED":
                r.active = False
                if r.kind == "tp1_watch":
                    out["tp1_filled"] = True
            elif g["status"] == "CANCELED":
                r.active = False
            elif g["status"] == "UNKNOWN":                # 모르는 상태는 닫힘이 아니다 · 예약 유지 + 알림 1번
                await self._alert_once(s, plan, f"unknown_order:{r.id}", "warning", "접수된 매도 상태 모름",
                                       "접수된 매도 주문의 상태를 알 수 없어 예약을 유지합니다. 직접 확인해 주십시오.")
            else:
                r.qty = int(g.get("remaining") or r.qty)

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

    @staticmethod
    def _kind_state(plan: Plan) -> str:
        """다리 값 종류를 정하는 상태 · HALTED 면 정지 직전 상태(추적 중이었으면 추적 값)."""
        return (plan.prev_state or state.HOLDING) if plan.state == state.HALTED else plan.state

    def _values_for(self, plan: Plan, seq: int, session: str, cur: Decimal) -> Values:
        p = params_of(plan)
        if session == "off":
            return sess.emergency_values(cur)
        if self._kind_state(plan) == state.TRAILING:
            return sess.trail_values(plan.avg_price or 0, plan.peak_price or cur)
        pcts = tuple(D(x) for x in p.get("ladder_pcts") or sess.DEFAULT_LADDER_PCTS)
        return sess.ladder_values(plan.avg_price or cur, pcts)[min(seq, len(pcts)) - 1]

    # ───────────────── 다리 등록 · 수정 · 취소 ─────────────────
    async def _cancel_leg(self, s, plan: Plan, leg: PlanLeg) -> None:
        if leg.toss_id and leg.status == "WATCHING":
            await self._cancel_leg_orders(s, plan, leg)
        leg.status = "CANCELED"
        await s.flush()

    def _avg_missing(self, plan: Plan) -> bool:
        """평균가가 없으면 사다리 · 추적 값을 계산할 수 없다 (0 으로 대신하지 않는다)."""
        return not plan.avg_price

    async def _register_leg(self, s, plan: Plan, seq: int, qty: int, vals: Values, tag: str,
                            allow_cross: bool = True, reset_loops: bool = True) -> Optional[PlanLeg]:
        if self._sell_stopped(plan):
            return None
        if str(seq) in (runtime_of(plan).get("cross_blocked") or []):
            return None                                       # 거절 3번 되풀이로 멈춘 다리 번호 · 정지를 풀 때까지 다시 시도하지 않음
        cid = self._cid(plan, "sl", seq)
        leg = PlanLeg(plan_id=plan.id, role="sl", seq=seq, kind="cond", client_order_id=cid, qty=qty,
                      watch_price=float(vals.watch), order_price=float(vals.order), status="UNCERTAIN", tag=tag,
                      expire_date=self._expire())
        s.add(leg)
        await s.flush()
        line = await ob.send(s, plan, cid=cid, kind="cond", role="sl", side="SELL", qty=qty, price=vals.order,
                             watch=vals.watch, leg=leg, now=self.clock())
        self._bump_cid(plan, "sl", seq)                       # 보낼 때마다 장부 한 줄 · 새 키
        await s.commit()                                      # 토스 호출 전에 기록
        try:
            res = await self.gate.place_stop(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=vals.watch,
                                             order=vals.order, client_id=cid, expire=self._expire(),
                                             check=self._stop_check(plan, vals.watch))
        except ExecutionError as exc:
            return await self._after_register_failure(s, plan, leg, "sl", seq, exc, line)
        if res.kind == "cond":
            leg.toss_id, leg.status = res.id, "WATCHING"
            ob.mark_open(line, res.id)
            if reset_loops:                                   # 거절 뒤 다시 거는 중이면 횟수를 지우지 않는다 (3번 되풀이 세기)
                self._reset_reject_loops(plan, seq)
            await s.commit()
            return leg
        ob.mark_not_created(line)                             # 조건주문이 만들어지지 않았다 (이미 넘음 · 점검 실패 · 확인 못 함)
        await s.delete(leg)
        await s.commit()
        if res.kind == "invalid":
            await self._sanity_reject(s, plan, f"손절 다리 {seq}", res.reason)
            return None
        if res.kind == "cross" and allow_cross:
            await self._sell_cross(s, plan, seq=seq, qty=qty, cur=res.cur, kind="immediate", old_leg=None, tag=tag)
        return None   # unconfirmed · 다음 걸음에 모자람으로 다시 본다

    async def _modify_leg(self, s, plan: Plan, leg: PlanLeg, *, qty: Optional[int] = None,
                          vals: Optional[Values] = None) -> bool:
        """수정(취소 뒤 새로 만들기) · 장부에 「옛 줄은 살아 있음 + 새 줄은 보냄-모름」 으로 함께 적는다 · 방향 문(6-1)을 거친다.
        반환: 수정했거나, 이미 넘어 즉시 매도로 처리했으면 True (호출 쪽이 같은 일을 다시 시도하지 않게). 못 했으면 False."""
        if self._sell_stopped(plan):
            return False
        if await ob.has_unresolved_for_leg(s, leg.id):
            return False                                      # 결과를 모르는 수정이 있으면 판정될 때까지 새로 보내지 않는다
        v = vals or Values(D(leg.watch_price), D(leg.order_price))
        q = int(qty if qty is not None else leg.qty)
        old_line = await ob.latest_open_line(s, leg.id)
        cid = self._cid(plan, "sl", leg.seq)
        line = await ob.send(s, plan, cid=cid, kind="cond", role="sl", side="SELL", qty=q, price=v.order, watch=v.watch,
                             leg=leg, replaces=old_line, now=self.clock())
        self._bump_cid(plan, "sl", leg.seq)                   # 보낼 때마다 새 키
        await s.commit()                                      # 토스 호출 전에 수정 기록
        try:
            res = await self.gate.place_stop(s, plan_id=plan.id, symbol=plan.symbol, qty=q, watch=v.watch,
                                             order=v.order, client_id=cid, expire=self._expire(),
                                             modify_id=leg.toss_id, check=self._stop_check(plan, v.watch))
        except ExecutionError as exc:
            leg.error_count += 1
            if definitely_not_created(exc):
                ob.mark_not_created(line)                     # 분명히 거절 · 옛 다리 그대로
            await self._event(s, plan, "leg_modify_fail", f"sl{leg.seq} {exc.__class__.__name__} #{leg.error_count}")
            if leg.error_count >= MAX_LEG_ERRORS:
                await self._halt(s, plan, f"다리 sl{leg.seq} 수정 {MAX_LEG_ERRORS}번 실패")
            await s.commit()
            return False   # 결과를 모르면 새 줄은 보냄-모름으로 남고 옛 다리는 살아 있는 것으로 둔다 (장부 대조가 판정)
        if res.kind == "invalid":
            ob.mark_not_created(line)
            await s.commit()
            await self._sanity_reject(s, plan, f"손절 다리 {leg.seq} 수정", res.reason)
            return False       # 옛 다리는 그대로 둔다
        if res.kind == "cond":
            leg.toss_id, leg.qty = res.id, q
            leg.watch_price, leg.order_price, leg.client_order_id = float(v.watch), float(v.order), cid
            leg.expire_date = self._expire()                  # 수정은 취소 뒤 새로 만들기라 만료일도 다시 적는다 (필수 칸)
            leg.error_count = 0
            ob.mark_open(line, res.id)
            if old_line is not None:
                old_line.state, old_line.resolved_at = ob.CLOSED, utcnow()
            self._reset_reject_loops(plan, leg.seq)
            await s.commit()
            return True
        if res.kind == "cross":
            if res.old_gone:
                line.state, line.resolved_at = ob.CLOSED, utcnow()
                if old_line is not None:
                    old_line.state, old_line.resolved_at = ob.CLOSED, utcnow()
                leg.status = "CANCELED"
                await self._event(s, plan, "leg_old_gone", f"sl{leg.seq} 수정 도중 방향이 뒤집혀 옛 다리도 새 다리도 없음 · 즉시 매도로 처리")
            else:
                ob.mark_not_created(line)
            await s.commit()
            handled = await self._sell_cross(s, plan, seq=leg.seq, qty=q, cur=res.cur, kind="immediate",
                                             old_leg=None if res.old_gone else leg, tag=leg.tag)
            return handled                                    # 처리됐으면 True · 호출 쪽이 다시 시도하지 않는다
        ob.mark_not_created(line)
        await s.commit()
        return False  # unconfirmed · 옛 다리는 그대로 둔다

    def _stop_check(self, plan: Plan, watch):
        """7-6: 사다리 · 비상 · 시간 손절 = 직전가 ±40% · 추적 = 감시가 ≤ 현재가 − 1틱."""
        if plan.state == state.TRAILING:
            return lambda cur: sanity.check_trail(watch, cur)
        return lambda cur: sanity.check_band(watch, cur, "손절 감시")

    async def _sanity_reject(self, s, plan: Plan, what: str, why: str) -> None:
        await self._event(s, plan, "sanity_reject", f"{what}: {why}")
        await self._alert_once(s, plan, f"sanity:{what}", "warning", "등록 거부 · 값 점검",
                               f"{what} 등록을 거부했습니다. {why}")

    # ───────────────── 6-1 이미 넘은 다리 → 즉시 지정가 매도 ─────────────────
    def _reset_reject_loops(self, plan: Plan, seq: int) -> None:
        loops = dict(runtime_of(plan).get("reject_loops") or {})
        if str(seq) in loops:
            loops.pop(str(seq))
            set_runtime(plan, reject_loops=loops)

    def _bump_reject_loops(self, plan: Plan, seq: int) -> int:
        loops = dict(runtime_of(plan).get("reject_loops") or {})
        loops[str(seq)] = int(loops.get(str(seq), 0)) + 1
        set_runtime(plan, reject_loops=loops)
        return loops[str(seq)]

    async def _sell_cross(self, s, plan: Plan, *, seq: int, qty: int, cur: Decimal, kind: str,
                          old_leg: Optional[PlanLeg], tag: str = "") -> bool:
        """이미 넘은 다리 처리: 대기 매수 취소 → 그 다리를 먼저 줄임 → 바로 지정가 매도 · 예약 장부에 올림."""
        if self._sell_stopped(plan):
            return False
        if str(seq) in (runtime_of(plan).get("cross_blocked") or []):
            return False                                      # 거절 3번 되풀이로 멈춘 번호 (정지를 풀 때까지 반복하지 않음)
        now = self.clock()
        f = self.limit_factor(now)
        if f is None:
            await self._alert_once(s, plan, f"limit_unavail:{seq}", "critical", "지정가를 낼 수 없는 시간대",
                                   f"손절 다리 {seq} 가 이미 넘었지만 지금은 지정가를 낼 수 없어 기존 다리를 그대로 둡니다.")
            return False
        # 주문가는 직전에 받은 값이 아니라 방금 다시 읽은 현재가로 정한다 (읽기 실패면 넘겨받은 값)
        try:
            cur = await self.gate.current(s, plan.symbol)
        except ExecutionError:
            pass
        # 수량 상한 = min(요청 수량, 계획 수량 · 계좌 보유 중 작은 값 − 이미 접수된 매도) · 0 이면 내지 않는다
        base, accepted, _ = await self._base_and_accepted(s, plan)
        cap = max(0, base - accepted)
        if qty > cap:
            await self._event(s, plan, "sell_qty_capped", f"sl{seq} {qty} → {cap}")
            qty = cap
        if qty <= 0:
            return False
        await self._cancel_pending_buys(s, plan)
        if old_leg is not None:
            await self._cancel_leg(s, plan, old_leg)       # 다리를 먼저 줄인다 (매도 합 ≤ 보유)
        price = sell_order(D(cur) * f)
        cid = self._cid(plan, "x", seq)
        resv = await sizing.reserve(s, plan.id, kind, qty, None)
        resv.leg_seq, resv.order_price, resv.client_order_id = seq, float(price), cid
        resv.uncertain = True                                  # 호출 전에 「확인 대기」 로 commit (결과를 못 받아도 장부 대조가 판정)
        await s.flush()
        line = await ob.send(s, plan, cid=cid, kind="limit", role="sell", side="SELL", qty=qty, price=price, resv=resv,
                             now=self.clock())
        self._bump_cid(plan, "x", seq)                         # 보낼 때마다 새 키
        await s.commit()
        try:
            oid = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, price=price,
                                             client_id=cid)
        except ExecutionError as exc:
            if not definitely_not_created(exc):               # 낸 결과를 모른다 → 예약을 그대로 두고 확인 대기 (이미 uncertain)
                await self._event(s, plan, "sell_uncertain", f"sl{seq} {exc.__class__.__name__} · 확인 대기")
                await s.commit()
                return True
            resv.active, resv.uncertain = False, False
            ob.mark_not_created(line)
            await self._event(s, plan, "sell_rejected", f"sl{seq} {exc.__class__.__name__}")
            await s.commit()
            await self._after_reject(s, plan, seq=seq, qty=qty, old=old_leg, tag=tag)
            return False
        resv.order_ref, resv.uncertain = oid, False
        ob.mark_open(line, oid)
        await self._event(s, plan, "sell_cross", f"sl{seq} qty {qty}")
        await s.commit()
        return True

    async def _after_reject(self, s, plan: Plan, *, seq: int, qty: int, old: Optional[PlanLeg], tag: str) -> None:
        """매도 거절 → 그 수량의 다리를 「6-1 을 통과하는 값」으로 다시 건다. 같은 다리에서 3번 되풀이되면 HALTED · 그 번호는 멈춤."""
        loops = self._bump_reject_loops(plan, seq)
        if loops >= MAX_REJECT_LOOPS:
            blocked = list(runtime_of(plan).get("cross_blocked") or [])
            if str(seq) not in blocked:
                blocked.append(str(seq))
                set_runtime(plan, cross_blocked=blocked)       # 정지 상태에서도 같은 즉시 매도를 되풀이하지 않는다
            await self._halt(s, plan, f"손절 다리 {seq} 매도 거절 {MAX_REJECT_LOOPS}번 되풀이 · 통과하는 다리만 남김")
            return
        cur = await self.gate.current(s, plan.symbol)
        tried: list[Values] = []
        if old is not None and old.watch_price:
            tried.append(Values(D(old.watch_price), D(old.order_price)))
        emergency_w = ceil_tick(cur * sess.EMERGENCY_FACTOR)
        tried.append(Values(emergency_w, order_price_from_watch(emergency_w, sess.OFFHOURS_FACTOR)))
        for v in tried:
            leg = await self._register_leg(s, plan, seq, qty, v, tag="emergency", allow_cross=False, reset_loops=False)
            if leg is not None:
                return
            if any(l.status == "UNCERTAIN" for l in await s.scalars(select(PlanLeg).where(
                    PlanLeg.plan_id == plan.id, PlanLeg.seq == seq, PlanLeg.role == "sl"))):
                return                                         # 낸 결과를 모르면 더 시도하지 않고 확인을 기다린다
        await self._halt(s, plan, f"손절 다리 {seq} 를 다시 걸지 못함")

    # ───────────────── 불변식 · 사다리 ─────────────────
    async def _base_and_accepted(self, s, plan: Plan) -> tuple[int, int, int]:
        pq = await sizing.plan_qty(s, plan)
        acct = await self.gate.account_qty(s, plan.id, plan.symbol)
        acc = await sizing.accepted_sell(s, plan.id)
        if acct < pq:
            await self._event(s, plan, "account_short", f"plan_qty {pq} account {acct}")
        return sizing.compute_base(pq, acct), acc, pq

    async def ensure_ladder(self, s, plan: Plan, *, emergency: bool = False) -> str:
        """체결 · 전이 · 다시 맞추기 직후 불변식 검사 (5절 10항). 반환: ok | fixed | halted | skipped.

        emergency=True 면 모자란 수량을 비상 손절 값(7-1)의 다리로 건다 (시간 손절 종료 1분 전 되돌림)."""
        if plan.state in (state.DRAFT, state.APPROVED, state.CLOSED, state.CANCELLED, state.ENTRY_ARMED,
                          state.ENTRY_RETRY, state.ADOPT_PENDING):
            return "skipped"
        if self._sell_stopped(plan):
            return "skipped"                    # Kill Switch 「매도도 멈춤」 · 어떤 경로로도 다리를 다시 걸지 않는다
        if plan.state == state.HALTED and plan.prev_state in PRE_HOLD_STATES:
            return "skipped"                    # 보유 전 정지(인수 대기 · 진입) 는 보호할 보유가 없다
        if self._avg_missing(plan):
            await self._alert_once(s, plan, "avg_missing", "critical", "평균가 없음",
                                   "평균가를 알 수 없어 손절 다리를 계산하지 못했습니다. 등록을 멈추고 직접 확인해 주십시오.")
            return "skipped"
        base, acc, pq = await self._base_and_accepted(s, plan)
        legs = await sizing.live_sl_legs(s, plan.id)
        seqs = [l.seq for l in legs]
        dup = len(seqs) != len(set(seqs))
        exp = await ob.exposure(s, plan.id)                     # 결과 모르는 손절 줄 (묶인 새 다리 · 수정 중 새 줄)
        unc_seqs = {l.seq for l in await s.scalars(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "sl", PlanLeg.status == "UNCERTAIN"))}
        unc_seqs |= await ob.bound_seqs(s, plan.id)             # 결과 모르는 줄이 걸린 번호는 새로 등록하지 않는다
        modifying = await ob.modifying_leg_ids(s, plan.id)      # 수정 결과를 모르는 다리는 건드리지 않는다
        target = sizing.sl_target(base, acc)
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in legs], dup_pairs=dup)   # 보호 수량에는 확인된 것만
        if rep.status == "ok":
            return "ok"
        now = self.clock()
        session = "off" if emergency else self._session(now)
        tag = "emergency" if emergency else session
        cur = await self.gate.current(s, plan.symbol)
        if rep.status == "excess":
            if dup:
                await self._halt(s, plan, "같은 번호의 손절 다리가 둘 이상 (짝이 여럿)")
                return "halted"
            return await self._shrink_sl(s, plan, legs, rep.target, skip_ids=modifying)    # 줄이기는 허용 (수정 중 다리만 뺀다)
        if exp["unknown_modify"] and sizing.exposure_over(sum(l.qty for l in legs), exp["unknown_modify"], target):
            await self._alert_once(s, plan, "exposure_possible", "critical", "손절 합이 넘칠 수 있음",
                                   "수정한 주문의 결과를 모르는데 옛 다리가 살아 있다면 매도 합이 보유를 넘습니다. 결과를 확인할 때까지 새로 걸지 않습니다.",
                                   every_sec=ob.REPEAT_ALERT_SEC)
            return "skipped"                                    # 새 모자람 등록만 막는다 (넘침 검사에는 옛 다리와 새 줄을 둘 다 센다)
        # 모자람 · HALTED 에서도 허용 · ⑨ 알림
        if plan.state == state.HALTED and not self._live_on(plan):
            pass  # 보호 다리 다시 걸기는 스위치와 무관하게 허용 (손절을 지우면 위험이 커진다)
        missing = rep.delta - exp["bound_new"]                  # 결과를 모르는 새 다리의 수량만 묶고 나머지 보호는 계속 건다
        if missing <= 0:
            return "skipped"
        await self._alert(plan, "warning", "손절 다리 모자람", f"{missing}주분 보호 다리를 다시 겁니다.")
        if not legs:
            free_seqs = [i for i in (1, 2, 3) if i not in unc_seqs]          # 결과 모르는 다리의 번호는 비워 둔다
            parts = sizing.split_ladder(missing, len(free_seqs)) if free_seqs else []
            for seq, q in zip(free_seqs, parts):
                await self._register_leg(s, plan, seq, q, self._values_for(plan, seq, session, cur), tag=tag)
        else:
            free = [i for i in (1, 2, 3) if i not in seqs and i not in unc_seqs]
            if free:
                await self._register_leg(s, plan, free[0], missing, self._values_for(plan, free[0], session, cur),
                                         tag=tag)
            else:
                cand = [l for l in legs if l.id not in modifying]
                if not cand:
                    return "skipped"
                last = cand[-1]
                await self._modify_leg(s, plan, last, qty=last.qty + missing,
                                       vals=self._values_for(plan, last.seq, session, cur))
                last.tag = tag
        return "fixed"

    async def _shrink_sl(self, s, plan: Plan, legs: list[PlanLeg], target: int, skip_ids: Optional[set] = None) -> str:
        """넘친 다리 축소 (마지막 번호부터) · 정상 넘침(발동 직후)은 바로 줄인다 · 줄이기가 3번 실패하면 HALTED."""
        extra = sum(l.qty for l in legs) - target
        for leg in sorted(legs, key=lambda l: -l.seq):
            if extra <= 0:
                break
            if skip_ids and leg.id in skip_ids:
                continue                                         # 수정 결과를 모르는 다리는 건드리지 않는다
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
        if self._sell_stopped(plan):
            # 매도도 멈춤 · 상태와 상관없이(정지 중에도) 등록 · 수정 · 매도 없이 남은 주문만 지운다
            await self._kill_all(s, plan)
            return
        self.gate.begin_tick()                      # 이 걸음 안에서는 계좌 보유를 한 번만 읽는다
        out = await self.sync_orders(s, plan)
        if plan.state == state.HALTED and plan.prev_state == state.ADOPT_PENDING:
            await self._cancel_pending_buys(s, plan)
            n, _ = await self._foreign_conds(s, plan)
            await state.transition(s, plan, state.CANCELLED, reason="인수 대기 중 정지 = 인수 취소")
            await self._alert(plan, "critical", "인수 취소 · 보호 없음",
                              f"인수 대기 중 정지해 인수를 취소했습니다. 이 종목에 앱 매도 주문이 {n}건 남아 있고 이 계획의 손절은 걸리지 않았습니다.")
            return

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
        pre_hold_halt = plan.state == state.HALTED and plan.prev_state in PRE_HOLD_STATES
        if pre_hold_halt:
            if plan.prev_state in (state.ENTRY_ARMED, state.ENTRY_RETRY) and pq > 0:
                await self._protect_partial_entry(s, plan)   # 정지 전에 일부 체결됐다 → 보유로 보고 손절 다리를 건다 (정지는 그대로)
            return                                  # 그 밖의 보유 전 정지는 닫지도 보호하지도 않는다 (재개하면 진입으로 돌아감)
        if pq <= 0 and not await self._active_reservations(s, plan):
            await self._close(s, plan)
            return
        await self._track_peak(s, plan, now)
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
        legs = await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status.in_(("WATCHING", "UNCERTAIN"))))
        for leg in list(legs):
            try:
                await self._cancel_leg_keep_unknown(s, plan, leg)
            except ExecutionError:
                if not (leg.status == "UNCERTAIN" or await ob.has_unresolved_for_leg(s, leg.id)):
                    leg.status = "CANCELED"
        if await ob.unresolved_lines(s, plan.id):                 # 모름 줄이 남으면 닫지 않고 정지 · 사람 확인 대기
            if plan.state != state.HALTED:
                await self._halt(s, plan, "결과 모르는 주문이 남아 있어 닫지 않습니다 · 화면에서 확인해 주십시오")
            return
        if plan.state != state.CLOSED:
            await state.transition(s, plan, state.CLOSED, reason="plan_qty 0")

    async def _kill_all(self, s, plan: Plan) -> None:
        """Kill Switch 「매도도 멈춤」 · 계획의 모든 조건주문 취소 · HALTED (1절 4항). 정지 중에도 남은 주문을 계속 지운다."""
        legs = await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status.in_(("WATCHING", "UNCERTAIN"))))
        for leg in list(legs):
            try:
                await self._cancel_leg_keep_unknown(s, plan, leg)    # 아는 번호는 취소 · 모름 줄이 있으면 상태는 확정하지 않고 알림
            except ExecutionError:
                pass
        resv = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.active.is_(True),
            PlanSellReservation.kind != "triggered", PlanSellReservation.order_ref.is_not(None))))
        for r in resv:                                  # 접수된 지정가 매도도 멈춘다 (취소 전 · 후 체결을 읽어 장부에 더함)
            try:
                if await self._cancel_resv(s, plan, r) is not None:
                    r.active = False
            except ExecutionError:
                pass
        if plan.state != state.HALTED:
            await self._halt(s, plan, "Kill Switch · 모든 주문 멈춤")

    # ── 진입 ──
    async def _tick_entry(self, s, plan: Plan, out: dict, now: datetime, sw_live: bool, killed: bool) -> None:
        if out["buy_filled"] or await sizing.plan_qty(s, plan) > 0:
            await self._on_buy_filled(s, plan)         # 일부라도 체결됐으면 스위치 · Kill Switch 와 상관없이 보유로 넘겨 손절을 건다
            return
        p = params_of(plan)
        close_at = p.get("entry_close_at")
        buy_leg = await s.scalar(select(PlanLeg).where(
            PlanLeg.plan_id == plan.id, PlanLeg.role == "buy", PlanLeg.status.in_(("WATCHING", "UNCERTAIN"))))
        if killed or not sw_live:
            if buy_leg:
                await self.cancel_buys_on_switch_off(s, plan)
            return
        if plan.state == state.ENTRY_ARMED and buy_leg is None and runtime_of(plan).get("rearm_buy") \
                and not (close_at and now >= parse_dt(close_at)):
            set_runtime(plan, rearm_buy=False)                # 정지 · 스위치 끄기로 지워진 매수를 재개 때 한 번만 다시 건다
            await self._place_buy(s, plan)
            return
        if plan.state == state.ENTRY_ARMED and close_at and now >= parse_dt(close_at):
            await self._cancel_pending_buys(s, plan)           # 마감 처리
            if await sizing.plan_qty(s, plan) > 0:
                await self._on_buy_filled(s, plan)
            else:
                await state.transition(s, plan, state.ENTRY_RETRY, reason="마감 처리")
            return
        if plan.state == state.ENTRY_RETRY:
            end = p.get("entry_window_end")
            if end and now >= parse_dt(end):
                await state.transition(s, plan, state.CANCELLED, reason="진입 창 끝")
                return
            reg = self.regular_window(now)
            if buy_leg is None and reg and reg[0] + sess.SWAP_DELAY <= now < reg[1]:
                await self._place_buy(s, plan)                # 정규장 시작 1분 뒤 같은 조건으로 다시 낸다

    async def _protect_partial_entry(self, s, plan: Plan) -> None:
        """진입 중 일부 체결된 뒤 정지된 계획 · 대기 매수를 지우고 정지 직전 상태를 보유로 바꿔 손절 다리를 건다 (HALTED 유지)."""
        fills = list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "BUY")))
        tot = sum(f.qty for f in fills)
        if tot:
            plan.avg_price = sum(f.qty * f.price for f in fills) / tot
        await self._cancel_pending_buys(s, plan)
        plan.prev_state = state.HOLDING
        await self._event(s, plan, "partial_entry_protected", f"체결 {tot}주 · 정지 중에도 손절 다리를 건다")
        await self.ensure_ladder(s, plan)

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
        foreign, rows = await self._foreign_conds(s, plan)
        set_runtime(plan, adopt_foreign=rows, adopt_checked_at=now.isoformat())
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

    async def _foreign_conds(self, s, plan: Plan) -> tuple[int, list[dict]]:
        """그 종목의 계획 밖 조건주문과 계획 밖 일반 매도 주문(앱에서 건 것)을 센다 (8-1)."""
        own = {l.toss_id for l in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)) if l.toss_id}
        own |= {r.order_ref for r in await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id)) if r.order_ref}
        rows = [{"toss_id": o.get("id"), "qty": o.get("qty"), "watch": _num(o.get("watch")), "order": _num(o.get("order")),
                 "side": o.get("side"), "kind": "cond"}
                for o in await self.gate.cond_open_list(s, plan.symbol) if o and o.get("id") not in own]
        rows += [{"toss_id": o.get("id"), "qty": o.get("qty"), "watch": None, "order": _num(o.get("price")),
                  "side": o.get("side"), "kind": "order"}
                 for o in await self.gate.limit_open_list(s, plan.symbol)
                 if o and o.get("id") not in own and str(o.get("side") or "").upper() == "SELL"]
        return len(rows), rows

    # ── TP1 ──
    async def _tp1_step(self, s, plan: Plan, sw_live: bool) -> None:
        p = params_of(plan)
        if plan.state != state.HOLDING or not p.get("tp1_watch"):
            return
        if await sizing.live_tp1_leg(s, plan.id) is not None:
            return
        if await s.scalar(select(PlanLeg.id).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "tp1",
                                                   PlanLeg.status == "UNCERTAIN").limit(1)) is not None:
            return                                   # 낸 결과를 모르는 TP1 이 있으면 찾아 이을 때까지 다시 내지 않는다
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
        if self._avg_missing(plan):
            await self._alert_once(s, plan, "avg_missing", "critical", "평균가 없음", "평균가를 알 수 없어 TP1 을 등록하지 않았습니다.")
            return
        why = sanity.check_tp1(watch, plan.avg_price or 0)
        if why:                                  # 7-6: 위반이면 등록 거부 + 알림 (같은 사유로 반복 알리지 않음)
            if not runtime_of(plan).get("tp1_sanity_alerted"):
                set_runtime(plan, tp1_sanity_alerted=True)
                await self._sanity_reject(s, plan, "TP1", why)
            return
        if sizing.must_use_tp1_watch(acct, pq) or p.get("tp1_mode") == "watch":
            set_runtime(plan, tp1_mode="watch")
            await self._tp1_watch_mode(s, plan, qty, watch)
            return
        cid = self._cid(plan, "tp", 1)
        leg = PlanLeg(plan_id=plan.id, role="tp1", seq=1, kind="cond", client_order_id=cid, qty=qty,
                      watch_price=float(watch), order_price=float(order), status="UNCERTAIN", expire_date=self._expire())
        s.add(leg)
        await s.flush()
        tp_line = await ob.send(s, plan, cid=cid, kind="cond", role="tp1", side="SELL", qty=qty, price=order, watch=watch,
                                leg=leg, now=self.clock())
        self._bump_cid(plan, "tp", 1)
        await s.commit()                             # 토스 호출 전에 기록 (손절 다리와 같은 방식)
        try:
            res = await self.gate.place_tp1(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, watch=watch, order=order,
                                            client_id=cid, expire=self._expire())
        except OrderRejected:
            # U1: 합이 보유를 넘는 등록 거절 → TP1 감시 모드
            ob.mark_not_created(tp_line)
            await s.delete(leg)
            await s.commit()
            await self._tp1_watch_mode(s, plan, qty, watch)
            return
        except ExecutionError as exc:
            await self._after_register_failure(s, plan, leg, "tp", 1, exc, tp_line)
            return
        if res.kind == "cond":
            leg.toss_id, leg.status = res.id, "WATCHING"
            ob.mark_open(tp_line, res.id)
            set_runtime(plan, tp1_mode="register")
            await s.commit()
        else:
            ob.mark_not_created(tp_line)
            await s.delete(leg)
            await s.commit()
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
        cid = self._cid(plan, "tp", 2)
        resv = await sizing.reserve(s, plan.id, "tp1_watch", qty, None)
        resv.order_price, resv.client_order_id = float(price), cid
        resv.uncertain = True
        await s.flush()
        line = await ob.send(s, plan, cid=cid, kind="limit", role="sell", side="SELL", qty=qty, price=price, resv=resv,
                             now=self.clock())
        self._bump_cid(plan, "tp", 2)
        await s.commit()                             # 호출 전에 「확인 대기」 로 commit
        try:
            resv.order_ref = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=qty, price=price,
                                                        client_id=cid)
            resv.uncertain = False
            ob.mark_open(line, resv.order_ref)
        except ExecutionError as exc:
            if not definitely_not_created(exc):
                await s.commit()                     # 낸 결과를 모른다 → 확인 대기 유지 (장부 대조가 판정)
                return
            resv.active, resv.uncertain = False, False
            ob.mark_not_created(line)
            await self.ensure_ladder(s, plan)     # 거절 → 다리 원래대로
            return
        await self._event(s, plan, "tp1_watch_sell", f"qty {qty}")

    def _held_price(self, plan: Plan, cur: Decimal, now: datetime) -> Decimal:
        """6-1 · 7-3 현재가 이상값 보류: 직전 값보다 10% 넘게 튄 값은 다음 읽기가 3% 안에서 확인해 줄 때까지 쓰지 않는다.
        같은 걸음 안에서는 한 번만 갱신한다 (두 번 불러도 자기 자신을 확인해 주지 않게)."""
        rt = runtime_of(plan)
        if rt.get("fp_at") == now.isoformat() and rt.get("fp") is not None:
            return D(rt["fp"])
        last, pend = sess.hold_jump(rt.get("fp"), rt.get("fp_pending"), float(cur))
        set_runtime(plan, fp=last, fp_pending=pend, fp_at=now.isoformat())
        return D(last)

    async def _track_peak(self, s, plan: Plan, now: datetime) -> None:
        """고점 = 정규장 1분봉 종가의 최고값 (7-3). 한 분 동안 마지막으로 읽은 값을 그 분의 종가로 보고, 분이 바뀔 때 반영한다.
        10% 넘게 튄 값은 다음 1분봉 종가가 3% 안에서 확인할 때까지 보류 · 정규장 밖 값은 쓰지 않는다."""
        try:
            cur = await self.gate.current(s, plan.symbol)
        except ExecutionError:
            return
        reg = self.regular_window(now)
        in_reg = bool(reg and reg[0] <= now < reg[1])
        minute = now.replace(second=0, microsecond=0).isoformat()
        rt = runtime_of(plan)
        bucket = rt.get("minute") or {}
        if bucket.get("m") and bucket["m"] != minute:
            if bucket.get("regular"):
                plan.peak_price, plan.pending_peak = sess.update_peak(plan.peak_price, plan.pending_peak, float(bucket["last"]))
            bucket = {}
        if not bucket:
            bucket = {"m": minute}
        bucket["last"], bucket["regular"] = float(cur), in_reg
        set_runtime(plan, minute=bucket)

    async def _on_tp1_filled(self, s, plan: Plan) -> None:
        """TP1 체결 → 추적 감시가 = max(평단, 정규장 고점 × 0.85) · 감시가 ≤ 현재가 − 1틱이면 추적 전환 · 아니면 익절 뒤 대기 (7-3)."""
        cur = await self.gate.current(s, plan.symbol)
        if self._avg_missing(plan):
            await self._halt(s, plan, "평균가를 알 수 없어 추적 값을 계산하지 못함")
            return
        peak = plan.peak_price or float(cur)
        v = sess.trail_values(plan.avg_price, peak)
        from .pricing import below_by_tick

        if below_by_tick(v.watch, cur):
            await state.transition(s, plan, state.TRAILING, reason="TP1 체결 · 추적 전환")
            await self._convert_to_trail(s, plan, v)
        else:
            await state.transition(s, plan, state.TP1_WAIT, reason="TP1 체결 · 익절 뒤 대기")
            await self.ensure_ladder(s, plan)    # 손절 다리 3건 수량만 불변식 A 로 줄임
        if runtime_of(plan).get("tp1_filled_human"):
            set_runtime(plan, tp1_filled_human=False)       # 실제로 처리한 뒤에만 표시를 지운다

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
        """추적 상향: 위로만 · 최소 폭 $0.005 또는 감시가의 0.5% 중 큰 값 (7-3). 현재가는 이상값 보류를 거친 값."""
        from .pricing import below_by_tick

        if self._avg_missing(plan):
            await self._alert_once(s, plan, "avg_missing", "critical", "평균가 없음", "평균가를 알 수 없어 추적을 멈춥니다.")
            return
        cur = self._held_price(plan, await self.gate.current(s, plan.symbol), now)
        v = sess.trail_values(plan.avg_price, plan.peak_price or cur)
        if plan.state == state.TP1_WAIT:
            if below_by_tick(v.watch, cur):
                await state.transition(s, plan, state.TRAILING, reason="추적 전환")
                await self._convert_to_trail(s, plan, v)
            return
        legs = await sizing.live_sl_legs(s, plan.id)
        if not legs or self._session(now) == "off":
            return
        old = D(legs[0].watch_price)
        w = min(v.watch, sess.cap_sell_watch(v.watch, cur))
        vv = Values(w, order_price_from_watch(w, sess.REGULAR_FACTOR))      # 주문가는 낮춘 감시가 기준
        if vv.watch > old and sess.trail_should_raise(old, vv.watch):
            for leg in legs:
                await self._modify_leg(s, plan, leg, vals=vv)    # 3건 하나씩 차례로

    # ── 세션 교대 ──
    async def _swap_session(self, s, plan: Plan, now: datetime) -> None:
        """시간대가 바뀌면 같은 3건을 수정한다 (정규장 사다리 ↔ 정규장 밖 비상 손절). 정지 중에는 값을 위로만 올린다."""
        if plan.state in (state.ENTRY_ARMED, state.ENTRY_RETRY, state.ADOPT_PENDING):
            return
        if self._avg_missing(plan):
            return
        session = self._session(now)
        legs = await sizing.live_sl_legs(s, plan.id)
        if not legs:
            return
        cur = await self.gate.current(s, plan.symbol)
        for leg in legs:
            if leg.tag == session:
                continue
            if leg.tag == "emergency" and plan.timestop_stage == "clean" and session == "regular":
                continue          # 시간 손절 종료 직전 비상 다리는 정규장이 끝날 때까지 그대로
            v = self._values_for(plan, leg.seq, session, cur)         # HALTED 면 정지 직전 상태(추적 등)의 값 종류
            if plan.state == state.HALTED and v.watch < D(leg.watch_price):
                leg.tag = session                                     # 정지 중에는 보호를 낮추지 않는다 (위로만)
                continue
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
            g = await self._cancel_resv(s, plan, r)                        # 읽기 → 취소 → 읽기 (빈 조회는 모름)
        except ExecutionError:
            return
        if g is None:
            return                                                         # 취소 뒤 확인 실패 → 다시 팔지 않고 예약을 묶어 둔다 (장부가 사람 확인으로)
        filled = int(g.get("filled") or 0)
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
        try:
            cur = await self.gate.current(s, plan.symbol)       # 다시 내는 가격도 방금 읽은 현재가로
        except ExecutionError:
            pass
        base, accepted, _ = await self._base_and_accepted(s, plan)
        remaining = min(remaining, max(0, base - accepted))     # 수량 상한 (계획 수량 · 계좌 보유 − 접수된 매도)
        if remaining <= 0:
            return
        price = sell_order(D(cur) * Decimal("0.95"))
        cid = self._cid(plan, "x", r.leg_seq or 0)
        new = await sizing.reserve(s, plan.id, r.kind, remaining, None)
        new.leg_seq, new.order_price, new.retries, new.client_order_id = r.leg_seq, float(price), r.retries + 1, cid
        new.uncertain = True
        await s.flush()
        line = await ob.send(s, plan, cid=cid, kind="limit", role="sell", side="SELL", qty=remaining, price=price,
                             resv=new, now=self.clock())
        self._bump_cid(plan, "x", r.leg_seq or 0)
        await s.commit()                             # 호출 전에 「확인 대기」 로 commit
        try:
            new.order_ref = await self.gate.sell_limit(s, plan_id=plan.id, symbol=plan.symbol, qty=remaining,
                                                       price=price, client_id=cid)
            new.uncertain = False
            ob.mark_open(line, new.order_ref)
        except ExecutionError as exc:
            if not definitely_not_created(exc):
                await s.commit()
                return
            new.active, new.uncertain = False, False
            ob.mark_not_created(line)
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
        today = now.strftime("%Y-%m-%d")
        if not sess.timestop_due(parse_dt(p["announce_at"]), now, self.holidays()):
            # 휴장일 반영으로 「아직 아님」이 되어도, 이미 끌어올리기 · 정리 단계에 들어간 오늘은 끝까지 간다 (종료 1분 전 취소 · 비상 다리 되돌리기가 돌아야 한다 · 1116-01 지킬 것 1)
            if not (plan.timestop_stage in ("lift", "clean") and plan.timestop_lift_session == today):
                return
        w = sess.timestop_window(reg)
        cur = self._held_price(plan, await self.gate.current(s, plan.symbol), now)     # 이상값 보류 (7-3)
        legs = await sizing.live_sl_legs(s, plan.id)
        if plan.timestop_stage in ("none", "lift") and plan.timestop_lift_session in (None, today) \
                and w.lift_from <= now < w.clean_from:
            last = runtime_of(plan).get("lift_last")
            if last and (now - datetime.fromisoformat(str(last))).total_seconds() < 15 * 60:
                return                                   # 15분마다 같은 계산으로 위로만 다시 수정
            plan.timestop_stage, plan.timestop_lift_session = "lift", today
            set_runtime(plan, lift_last=now.isoformat())
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
                if not r.order_ref:
                    continue
                try:
                    if await self._cancel_resv(s, plan, r) is not None:       # 빈 조회는 예약을 풀지 않는다
                        r.active = False
                except ExecutionError:
                    pass
            await self.ensure_ladder(s, plan, emergency=True)    # 그 수량은 비상 손절 값의 다리로 (6-1 거침)

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
        if self._sell_stopped(plan):
            raise state.TransitionError("Kill Switch 「매도도 멈춤」 중에는 재개할 수 없습니다")
        if await ob.unresolved_lines(s, plan.id):
            raise state.TransitionError("결과를 모르는 주문이 있습니다 · 화면에서 「체결 n주 / 안 만들어짐」 을 먼저 확인해 주십시오")
        set_runtime(plan, cross_blocked=[], reject_loops={})
        stale = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan.id, PlanSellReservation.active.is_(True),
            PlanSellReservation.order_ref.is_(None), PlanSellReservation.uncertain.is_(False),
            PlanSellReservation.kind != "triggered")))
        for r in stale:
            r.active = False                            # 주문 번호 없이 남은 예약은 정리한다 (영구히 보호 수량을 가리지 않게)
        if plan.prev_state in (state.ENTRY_ARMED, state.ENTRY_RETRY):
            set_runtime(plan, rearm_buy=True)
        if plan.state == state.HALTED and plan.prev_state in PRE_HOLD_STATES:
            return await state.resume(s, plan)              # 보유 전 정지는 불변식 대상이 아니다 (진입으로 돌아감)
        await self.ensure_ladder(s, plan)
        if plan.state != state.HALTED:
            raise state.TransitionError("다시 맞추는 중 다시 정지되었습니다")
        base, acc, _ = await self._base_and_accepted(s, plan)
        legs = await sizing.live_sl_legs(s, plan.id)
        rep = sizing.check_invariants(base=base, accepted_sell=acc, sl_qtys=[l.qty for l in legs])
        if rep.status != "ok":
            raise state.TransitionError("불변식을 통과하지 못해 재개할 수 없습니다")
        res = await state.resume(s, plan)
        if runtime_of(plan).get("tp1_filled_human") and plan.state == state.HOLDING:
            await self._on_tp1_filled(s, plan)               # 정지 중에 확정된 TP1 체결은 재개 때 처리한다 (TP1 을 다시 내지 않음)
        return res
