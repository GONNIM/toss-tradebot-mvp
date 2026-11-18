"""실제 · 모의 브로커와 감시 방향 문 · 계획서 1절 9항 · 6-1.

이 파일이 토스 조건주문 · 주문 API 를 부르는 유일한 곳이다(시험이 막는다).
- RealRaw: 토스 API 를 부른다(동기 클라이언트를 asyncio.to_thread 로).
- PaperRaw: 토스 주문 · 조건주문 API 를 한 번도 부르지 않는다. 시세만 읽고 체결은 가상(plan_paper_* 표).
- DirectionGate: 조건주문 등록 · 수정 · 일반 주문의 6-1 방향 규칙을 한 곳에서 거친다. raw.cond_create ·
  raw.cond_modify · raw.limit_create 는 이 클래스 안에서만 부른다.

[확인 못 함] 조건주문 응답 · 수정 요청 본문의 세부 모양은 이 저장소에 기록이 없다(U1~U9 소액 시험으로 확정).
RealRaw 의 파싱은 열쇠 이름을 너그럽게 받고, 모르는 상태는 UNKNOWN 으로 돌려 상위가 안전측(다시 맞추기)으로 간다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import select

from backend.execution.exceptions import ExecutionError, OrderRejected

from .models import PlanPaperOrder, PlanPaperPosition, utcnow
from .pricing import D, below_by_tick, fmt, tick
from .ws import PriceStore

logger = logging.getLogger(__name__)

# 토스가 「조건 이미 충족」 류로 등록을 거절할 때의 코드 (옛 문서 · 1.2.28 명세에는 없음 · 6-1)
_ALREADY_MET_CODES = {"condition-already-met", "trigger-condition-already-met"}


def _is_already_met(exc: OrderRejected) -> bool:
    code = (getattr(exc, "code", "") or "").lower()
    return code in _ALREADY_MET_CODES or ("condition" in code and "met" in code)


def is_sell_blocked_by_opposite(exc: Exception) -> bool:
    """`opposite-pending-order-exists` (같은 종목 대기 매수가 있어 매도 거절 · U9)."""
    return "opposite-pending-order-exists" in str(exc)


def access_token() -> str:
    """웹소켓 접속용 토큰 (REST 와 같은 토큰 · 발급은 toss_client 의 잠금 · 가드 안에서만)."""
    from backend.execution.brokers.toss_client import get_toss_client

    return get_toss_client().access_token()


# ─── 원시 브로커 ────────────────────────────────────────────────

class RawBroker:
    """공통 모양 (모두 async · s 는 DB 세션 · 모의가 쓴다 · 실제는 무시)."""

    mode = "base"

    async def last_price_rest(self, s, symbol: str) -> Optional[Decimal]: ...
    async def account_qty(self, s, plan_id: int, symbol: str) -> int: ...
    async def cond_create(self, s, *, plan_id: int, symbol: str, side: str, qty: int, watch: Decimal,
                          order: Decimal, client_id: str, expire: str) -> str: ...
    async def cond_modify(self, s, cond_id: str, *, plan_id: int, symbol: str, side: str, qty: int,
                          watch: Decimal, order: Decimal, client_id: str, expire: str) -> str: ...
    async def cond_cancel(self, s, cond_id: str) -> None: ...
    async def cond_get(self, s, cond_id: str) -> Optional[dict]: ...
    async def cond_open_list(self, s, symbol: Optional[str] = None) -> list[dict]: ...
    async def limit_create(self, s, *, plan_id: int, symbol: str, side: str, qty: int, price: Decimal,
                           client_id: str) -> str: ...
    async def limit_cancel(self, s, order_id: str) -> None: ...
    async def limit_get(self, s, order_id: str) -> Optional[dict]: ...

    async def limit_open_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        """열린 일반 주문 목록 · [{id, client_id, symbol, side, qty, price}] (찾지 못하면 빈 목록)."""
        return []

    async def cond_closed_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        """닫힌 조건주문 목록(체결 · 취소 · 만료) · 낸 결과를 모를 때 clientOrderId 로 찾는다."""
        return []

    async def limit_closed_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        return []

    async def buying_power_usd(self, s) -> Optional[float]:
        """계좌 USD 매수 가능 금액 (모의 · 시험 도구는 None = 확인 못 함)."""
        return None


def _to_int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


class RealRaw(RawBroker):
    mode = "real"

    def __init__(self, client=None):
        self._client = client

    def _c(self):
        if self._client is None:
            from backend.execution.brokers.toss_client import get_toss_client
            self._client = get_toss_client()
        return self._client

    async def _run(self, fn, *a, **k):
        return await asyncio.to_thread(fn, *a, **k)

    async def last_price_rest(self, s, symbol):
        data = await self._run(self._c().prices, [symbol])
        if isinstance(data, dict):
            data = data.get("items") or data.get("prices") or []
        if isinstance(data, list) and data:
            item = data[0]
            price = item.get("price") or item.get("lastPrice")
            if isinstance(price, dict):
                price = price.get("lastPrice") or price.get("close")
            if price is not None:
                return D(price)
        return None

    async def account_qty(self, s, plan_id, symbol):
        data = await self._run(self._c().holdings, symbol) or {}
        items = data.get("items") if isinstance(data, dict) else data
        for it in items or []:
            if it.get("symbol") == symbol:
                return _to_int(it.get("quantity"))
        return 0

    async def cond_closed_list(self, s, symbol=None):
        env = await self._run(self._c().list_conditional_orders, "CLOSED")
        res = env.result
        items = res if isinstance(res, list) else ((res or {}).get("items") or (res or {}).get("conditionalOrders") or [])
        out = [self._norm_cond(i) for i in items if isinstance(i, dict)]
        return [o for o in out if symbol is None or o["symbol"] == symbol]

    async def limit_closed_list(self, s, symbol=None):
        env = await self._run(self._c().list_orders, "CLOSED")
        res = env.result
        items = res if isinstance(res, list) else ((res or {}).get("items") or (res or {}).get("orders") or [])
        out = []
        for d in items:
            if isinstance(d, dict):
                o = {"id": str(d.get("orderId") or d.get("id") or ""), "client_id": d.get("clientOrderId"),
                     "symbol": d.get("symbol"), "side": str(d.get("side") or "").upper(),
                     "qty": _to_int(d.get("quantity")), "price": d.get("price")}
                if o["id"] and (symbol is None or o["symbol"] == symbol):
                    out.append(o)
        return out

    async def limit_open_list(self, s, symbol=None):
        """GET /orders?status=OPEN 을 너그럽게 읽는다(열쇠 이름 미확인 · 모르면 빈 목록 → 확인 못 함 쪽으로 안전하게)."""
        env = await self._run(self._c().list_orders, "OPEN")
        res = env.result
        items = res if isinstance(res, list) else ((res or {}).get("items") or (res or {}).get("orders") or [])
        out = []
        for d in items:
            if not isinstance(d, dict):
                continue
            o = {"id": str(d.get("orderId") or d.get("id") or ""), "client_id": d.get("clientOrderId"),
                 "symbol": d.get("symbol"), "side": str(d.get("side") or "").upper(),
                 "qty": _to_int(d.get("quantity")), "price": d.get("price")}
            if o["id"] and (symbol is None or o["symbol"] == symbol):
                out.append(o)
        return out

    async def buying_power_usd(self, s):
        """토스 buying-power(USD) · 응답 열쇠 이름은 미확인이라 흔한 이름 몇 개만 보고 없으면 None (확인 못 함)."""
        data = await self._run(self._c().buying_power, "USD")
        if isinstance(data, dict):
            for k in ("orderableAmount", "buyingPower", "orderable", "amount", "cash"):
                v = data.get(k)
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _cond_body(symbol, side, qty, watch, order, client_id, expire) -> dict:
        return {
            "clientOrderId": client_id, "type": "SINGLE", "symbol": symbol, "quantity": str(qty),
            "orderType": "LIMIT", "expireDate": expire,
            "first": {"orderSide": side, "triggerPrice": fmt(watch), "orderPrice": fmt(order)},
        }

    @staticmethod
    def _id_of(result) -> str:
        d = result if isinstance(result, dict) else {}
        cid = d.get("conditionalOrderId") or d.get("id") or d.get("orderId")
        if not cid:
            raise ExecutionError("토스 응답에 번호가 없습니다")
        return str(cid)

    async def cond_create(self, s, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        env = await self._run(self._c().create_conditional_order,
                              self._cond_body(symbol, side, qty, watch, order, client_id, expire))
        return self._id_of(env.result)

    async def cond_modify(self, s, cond_id, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        # 수정 본문은 등록 본문과 같은 모양으로 보낸다(미확인 · U6/U7). 수정은 취소 뒤 새 번호.
        env = await self._run(self._c().modify_conditional_order, cond_id,
                              self._cond_body(symbol, side, qty, watch, order, client_id, expire))
        return self._id_of(env.result)

    async def cond_cancel(self, s, cond_id):
        await self._run(self._c().cancel_conditional_order, cond_id)

    @staticmethod
    def _norm_cond(d: dict) -> dict:
        raw = str(d.get("status") or "").upper()
        status = {
            "WATCHING": "WATCHING", "PAUSED": "WATCHING", "PENDING": "WATCHING", "OPEN": "WATCHING",
            "TRIGGERED": "TRIGGERED", "ORDERED": "TRIGGERED",
            "FILLED": "FILLED", "COMPLETED": "FILLED",
            "CANCELED": "CANCELED", "CANCELLED": "CANCELED", "EXPIRED": "EXPIRED", "REJECTED": "REJECTED",
        }.get(raw, "UNKNOWN")
        first = d.get("first") or {}
        ex = d.get("execution") or {}
        return {
            "id": str(d.get("conditionalOrderId") or d.get("id") or ""),
            "status": status,
            "symbol": d.get("symbol"),
            "side": first.get("orderSide") or d.get("side"),
            "qty": _to_int(d.get("quantity")),
            "watch": first.get("triggerPrice"),
            "order": first.get("orderPrice"),
            "client_id": d.get("clientOrderId"),
            "order_id": d.get("orderId") or d.get("triggeredOrderId"),
            "filled": _to_int(ex.get("filledQuantity")),
            "remaining": _to_int(ex.get("remainingQuantity")),
            "avg": ex.get("averagePrice"),
        }

    async def cond_get(self, s, cond_id):
        env = await self._run(self._c().get_conditional_order, cond_id)
        return self._norm_cond(env.result) if isinstance(env.result, dict) else None

    async def cond_open_list(self, s, symbol=None):
        env = await self._run(self._c().list_conditional_orders, "OPEN")
        res = env.result
        items = res if isinstance(res, list) else ((res or {}).get("items") or (res or {}).get("conditionalOrders") or [])
        out = [self._norm_cond(i) for i in items if isinstance(i, dict)]
        return [o for o in out if symbol is None or o["symbol"] == symbol]

    async def limit_create(self, s, *, plan_id, symbol, side, qty, price, client_id):
        env = await self._run(self._c().create_order, {
            "clientOrderId": client_id, "symbol": symbol, "side": side, "orderType": "LIMIT",
            "timeInForce": "DAY", "quantity": str(qty), "price": fmt(price),
        })
        return self._id_of(env.result)

    async def limit_cancel(self, s, order_id):
        await self._run(self._c().cancel_order, order_id)

    async def limit_get(self, s, order_id):
        env = await self._run(self._c().get_order, order_id)
        d = env.result if isinstance(env.result, dict) else {}
        ex = d.get("execution") or {}
        raw = str(d.get("status") or "").upper()
        status = {"PENDING": "OPEN", "PARTIAL_FILLED": "OPEN", "PENDING_CANCEL": "OPEN", "PENDING_REPLACE": "OPEN",
                  "FILLED": "FILLED", "CANCELED": "CANCELED", "REJECTED": "CANCELED", "REPLACED": "CANCELED"}.get(raw, "UNKNOWN")
        return {"status": status, "filled": _to_int(ex.get("filledQuantity")),
                "remaining": _to_int(ex.get("remainingQuantity")), "avg": ex.get("averagePrice"),
                "symbol": d.get("symbol"), "side": d.get("side")}


class PaperRaw(RawBroker):
    """모의 · 토스 주문 · 조건주문 API 를 부르지 않는다. 시세 읽기 함수만 받는다.

    가상 체결 규칙(계획서 1절 9항): 감시는 모든 시간대 · 지정가는 가격이 주문가에 닿아야 체결 ·
    갭으로 주문가를 건너뛰면 미체결 · 감시 방향은 6-1 과 똑같이(등록 순간 현재가가 방향을 정함).
    """

    mode = "paper"

    def __init__(self, price_fn: Callable[[str], Any]):
        self._price_fn = price_fn   # async (symbol) → Decimal | None · 시세 읽기만

    async def last_price_rest(self, s, symbol):
        v = await self._price_fn(symbol)
        return None if v is None else D(v)

    async def _pos(self, s, plan_id, symbol) -> PlanPaperPosition:
        pos = await s.get(PlanPaperPosition, plan_id)
        if pos is None:
            pos = PlanPaperPosition(plan_id=plan_id, symbol=symbol, qty=0, avg_price=0.0)
            s.add(pos)
            await s.flush()
        return pos

    async def account_qty(self, s, plan_id, symbol):
        return int((await self._pos(s, plan_id, symbol)).qty)

    async def cond_create(self, s, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        cur = await self.last_price_rest(s, symbol)
        if cur is None:
            raise ExecutionError("모의 시세 없음")
        if D(watch) < cur:
            direction = "le"
        elif D(watch) > cur:
            direction = "ge"
        else:
            direction = "ge" if side == "SELL" else "le"   # 같으면 매도 이상 · 매수 이하
        row = PlanPaperOrder(plan_id=plan_id, symbol=symbol, kind="cond", side=side, qty=qty,
                             watch_price=float(watch), order_price=float(order), direction=direction,
                             client_order_id=client_id)
        s.add(row)
        await s.flush()
        return f"P{row.id}"

    async def cond_modify(self, s, cond_id, *, plan_id, symbol, side, qty, watch, order, client_id, expire):
        await self.cond_cancel(s, cond_id)
        return await self.cond_create(s, plan_id=plan_id, symbol=symbol, side=side, qty=qty, watch=watch,
                                      order=order, client_id=client_id, expire=expire)

    @staticmethod
    def _pid(cid: str) -> int:
        return int(str(cid).lstrip("P"))

    async def cond_cancel(self, s, cond_id):
        row = await s.get(PlanPaperOrder, self._pid(cond_id))
        if row is not None and row.status == "OPEN":
            row.status = "CANCELED"
            await s.flush()

    async def cond_get(self, s, cond_id):
        row = await s.get(PlanPaperOrder, self._pid(cond_id))
        if row is None:
            return None
        status = {"OPEN": "WATCHING", "TRIGGERED": "TRIGGERED", "FILLED": "FILLED", "CANCELED": "CANCELED"}[row.status]
        out = {"id": cond_id, "status": status, "symbol": row.symbol, "side": row.side, "qty": row.qty,
               "watch": row.watch_price, "order": row.order_price, "client_id": row.client_order_id,
               "order_id": None, "filled": 0, "remaining": row.qty, "avg": None}
        if row.child_id:
            child = await s.get(PlanPaperOrder, row.child_id)
            if child is not None:
                out["order_id"] = f"P{child.id}"
                if child.status == "FILLED":
                    out.update(status="FILLED", filled=child.qty, remaining=0, avg=child.order_price)
                elif child.status == "CANCELED":
                    out.update(status="CANCELED")
        return out

    async def cond_open_list(self, s, symbol=None):
        q = select(PlanPaperOrder).where(PlanPaperOrder.kind == "cond", PlanPaperOrder.status == "OPEN")
        if symbol:
            q = q.where(PlanPaperOrder.symbol == symbol)
        return [await self.cond_get(s, f"P{r.id}") for r in await s.scalars(q)]

    async def limit_create(self, s, *, plan_id, symbol, side, qty, price, client_id):
        row = PlanPaperOrder(plan_id=plan_id, symbol=symbol, kind="limit", side=side, qty=qty,
                             order_price=float(price), client_order_id=client_id)
        s.add(row)
        await s.flush()
        return f"P{row.id}"

    async def limit_cancel(self, s, order_id):
        row = await s.get(PlanPaperOrder, self._pid(order_id))
        if row is not None and row.status == "OPEN":
            row.status = "CANCELED"
            await s.flush()

    async def limit_get(self, s, order_id):
        row = await s.get(PlanPaperOrder, self._pid(order_id))
        if row is None:
            return None
        status = {"OPEN": "OPEN", "FILLED": "FILLED", "CANCELED": "CANCELED", "TRIGGERED": "OPEN"}[row.status]
        filled = row.qty if row.status == "FILLED" else 0
        return {"status": status, "filled": filled, "remaining": row.qty - filled,
                "avg": row.order_price if filled else None, "symbol": row.symbol, "side": row.side}

    async def limit_open_list(self, s, symbol=None):
        q = select(PlanPaperOrder).where(PlanPaperOrder.kind == "limit", PlanPaperOrder.status == "OPEN")
        if symbol:
            q = q.where(PlanPaperOrder.symbol == symbol)
        return [{"id": f"P{r.id}", "client_id": r.client_order_id, "symbol": r.symbol, "side": r.side, "qty": r.qty,
                 "price": r.order_price} for r in await s.scalars(q)]

    async def cond_closed_list(self, s, symbol=None):
        q = select(PlanPaperOrder).where(PlanPaperOrder.kind == "cond", PlanPaperOrder.status != "OPEN")
        if symbol:
            q = q.where(PlanPaperOrder.symbol == symbol)
        return [await self.cond_get(s, f"P{r.id}") for r in await s.scalars(q)]

    async def limit_closed_list(self, s, symbol=None):
        q = select(PlanPaperOrder).where(PlanPaperOrder.kind == "limit", PlanPaperOrder.status != "OPEN")
        if symbol:
            q = q.where(PlanPaperOrder.symbol == symbol)
        return [{"id": f"P{r.id}", "client_id": r.client_order_id, "symbol": r.symbol, "side": r.side, "qty": r.qty,
                 "price": r.order_price} for r in await s.scalars(q)]

    # ── 가상 체결 ──
    async def on_price(self, s, symbol: str, price) -> None:
        """시세 한 번에 가상 주문을 평가한다(조건 닿음 → 지정가 생성 → 주문가에 닿으면 체결)."""
        p = float(price)
        rows = list(await s.scalars(select(PlanPaperOrder).where(
            PlanPaperOrder.symbol == symbol, PlanPaperOrder.status == "OPEN").order_by(PlanPaperOrder.id)))
        for row in rows:
            if row.kind == "cond":
                hit = (row.direction == "le" and p <= row.watch_price) or (row.direction == "ge" and p >= row.watch_price)
                if hit:
                    row.status = "TRIGGERED"
                    child = PlanPaperOrder(plan_id=row.plan_id, symbol=symbol, kind="limit", side=row.side,
                                           qty=row.qty, order_price=row.order_price,
                                           client_order_id=(row.client_order_id or "") + "-t")
                    s.add(child)
                    await s.flush()
                    row.child_id = child.id
                    await self._try_fill(s, child, p)
            else:
                await self._try_fill(s, row, p)
        await s.flush()

    async def _try_fill(self, s, row: PlanPaperOrder, p: float) -> None:
        ok = (row.side == "SELL" and p >= row.order_price) or (row.side == "BUY" and p <= row.order_price)
        if not ok or row.status != "OPEN":
            return
        pos = await self._pos(s, row.plan_id, row.symbol)
        if row.side == "SELL":
            qty = min(row.qty, pos.qty)   # 가상 보유를 넘겨 팔지 못한다
            row.qty = qty
            pos.qty -= qty
        else:
            total = pos.qty * pos.avg_price + row.qty * row.order_price
            pos.qty += row.qty
            pos.avg_price = total / pos.qty if pos.qty else 0.0
        row.status = "FILLED"
        await s.flush()


# ─── 감시 방향 문 (6-1) ──────────────────────────────────────────

@dataclass
class GateResult:
    kind: str                   # cond | cross | unconfirmed | limit
    id: Optional[str] = None    # cond 번호 · limit 번호
    cur: Optional[Decimal] = None
    old_gone: bool = False      # 수정(취소 뒤 새로 만들기) 뒤 방향이 뒤집혀 취소해, 옛 다리도 이미 없다
    reason: str = ""            # kind == "invalid" (7-6 sanity 위반) 일 때 사유


class DirectionGate:
    """모든 조건주문 등록 · 수정 · 일반 주문이 거치는 단 하나의 문."""

    def __init__(self, raw: RawBroker, feed: Optional[PriceStore] = None, *, ws_max_age: float = 10.0):
        self.raw = raw
        self.feed = feed or PriceStore()
        self.ws_max_age = ws_max_age
        self._tick_active = False
        self._acct_cache: dict[tuple[int, str], int] = {}

    def begin_tick(self) -> None:
        """한 걸음 동안 계좌 보유 조회를 한 번만 한다 (조회 한도 절약). 주문을 내거나 취소하면 캐시를 비운다."""
        self._tick_active = True
        self._acct_cache = {}

    def _dirty(self) -> None:
        self._acct_cache = {}

    @property
    def mode(self) -> str:
        return self.raw.mode

    # ── 시세 ──
    async def current(self, s, symbol: str) -> Decimal:
        """등록 · 수정 직전 현재가: 웹소켓 최근 체결(10초 이내) 아니면 GET /prices."""
        ws = self.feed.fresh(symbol, self.ws_max_age)
        if ws is not None:
            return ws
        rest = await self.raw.last_price_rest(s, symbol)
        if rest is None:
            raise ExecutionError("현재가를 읽지 못했습니다")
        return rest

    async def _two_prices(self, s, symbol: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """낮은 현재가 확인용 두 값. 웹소켓 값이 낡았으면 REST 를 한 번 더 읽는다(웹소켓 미구현 구간)."""
        a = self.feed.fresh(symbol, self.ws_max_age)
        b = await self.raw.last_price_rest(s, symbol)
        if a is None:
            a = await self.raw.last_price_rest(s, symbol)
        return a, b

    async def confirmed_cross(self, s, symbol: str, watch: Decimal) -> bool:
        """두 값이 서로 1% 안에서 같고 둘 다 감시가 이하일 때만 True (한쪽만 낮으면 이상값)."""
        a, b = await self._two_prices(s, symbol)
        if a is None or b is None or a <= 0 or b <= 0:
            return False
        if abs(a - b) / max(a, b) > Decimal("0.01"):
            return False
        return a <= D(watch) and b <= D(watch)

    # ── 매도 손절 · 추적 · 비상 · 시간 손절 다리 ──
    async def place_stop(self, s, *, plan_id: int, symbol: str, qty: int, watch: Decimal, order: Decimal,
                         client_id: str, expire: str, modify_id: Optional[str] = None,
                         check: Optional[Callable[[Decimal], Optional[str]]] = None) -> GateResult:
        """감시가가 현재가 아래(≤ 현재가 − 1틱)면 조건주문. 아니면 이미 넘은 다리 → cross (두 값 확인 뒤).

        check(현재가) 는 7-6 sanity · 조건주문으로 걸 때만 본다(이미 넘은 다리의 즉시 매도는 막지 않는다).
        """
        self._dirty()
        cur = await self.current(s, symbol)
        if not below_by_tick(watch, cur):
            if await self.confirmed_cross(s, symbol, watch):
                return GateResult("cross", cur=cur)
            return GateResult("unconfirmed", cur=cur)
        if check is not None:
            why = check(cur)
            if why:
                return GateResult("invalid", cur=cur, reason=why)
        try:
            if modify_id:
                cid = await self.raw.cond_modify(s, modify_id, plan_id=plan_id, symbol=symbol, side="SELL", qty=qty,
                                                 watch=watch, order=order, client_id=client_id, expire=expire)
            else:
                cid = await self.raw.cond_create(s, plan_id=plan_id, symbol=symbol, side="SELL", qty=qty,
                                                 watch=watch, order=order, client_id=client_id, expire=expire)
        except OrderRejected as exc:
            if _is_already_met(exc):
                return GateResult("cross", cur=cur)
            raise
        # 등록 직후 다시 읽어 방향이 뒤집혔는지 본다
        cur2 = await self.current(s, symbol)
        if not below_by_tick(watch, cur2):
            await self.raw.cond_cancel(s, cid)
            return GateResult("cross", cur=cur2, old_gone=bool(modify_id))
        return GateResult("cond", id=cid, cur=cur2)

    # ── TP1 (등록 모드) ──
    async def place_tp1(self, s, *, plan_id: int, symbol: str, qty: int, watch: Decimal, order: Decimal,
                        client_id: str, expire: str, modify_id: Optional[str] = None) -> GateResult:
        """감시가 ≥ 현재가 + 1틱 이면 조건주문. 아니면 이미 넘음 → cross (TP1 감시 모드 처리)."""
        from .pricing import above_by_tick

        self._dirty()
        cur = await self.current(s, symbol)
        if not above_by_tick(watch, cur):
            return GateResult("cross", cur=cur)
        try:
            if modify_id:
                cid = await self.raw.cond_modify(s, modify_id, plan_id=plan_id, symbol=symbol, side="SELL", qty=qty,
                                                 watch=watch, order=order, client_id=client_id, expire=expire)
            else:
                cid = await self.raw.cond_create(s, plan_id=plan_id, symbol=symbol, side="SELL", qty=qty,
                                                 watch=watch, order=order, client_id=client_id, expire=expire)
        except OrderRejected as exc:
            if _is_already_met(exc):
                return GateResult("cross", cur=cur)
            raise
        cur2 = await self.current(s, symbol)
        if not above_by_tick(watch, cur2):
            await self.raw.cond_cancel(s, cid)
            return GateResult("cross", cur=cur2, old_gone=bool(modify_id))
        return GateResult("cond", id=cid, cur=cur2)

    # ── 매수 ──
    async def place_buy(self, s, *, plan_id: int, symbol: str, qty: int, watch: Decimal, order: Decimal,
                        client_id: str, expire: str,
                        check: Optional[Callable[[Decimal], Optional[str]]] = None) -> GateResult:
        """감시가 ≤ 현재가 − 1틱 이면 매수 조건주문. 아니면 일반 지정가(DAY) 매수. check 는 7-6 sanity."""
        self._dirty()
        cur = await self.current(s, symbol)
        if check is not None:
            why = check(cur)
            if why:
                return GateResult("invalid", cur=cur, reason=why)
        if below_by_tick(watch, cur):
            try:
                cid = await self.raw.cond_create(s, plan_id=plan_id, symbol=symbol, side="BUY", qty=qty,
                                                 watch=watch, order=order, client_id=client_id, expire=expire)
            except OrderRejected as exc:
                if not _is_already_met(exc):
                    raise
            else:
                cur2 = await self.current(s, symbol)
                if below_by_tick(watch, cur2):
                    return GateResult("cond", id=cid, cur=cur2)
                await self.raw.cond_cancel(s, cid)
        oid = await self.raw.limit_create(s, plan_id=plan_id, symbol=symbol, side="BUY", qty=qty, price=order,
                                          client_id=client_id)
        return GateResult("limit", id=oid, cur=cur)

    # ── 즉시 지정가 매도 (이미 넘은 다리 · TP1 감시 · 시간 손절) ──
    async def sell_limit(self, s, *, plan_id: int, symbol: str, qty: int, price: Decimal, client_id: str) -> str:
        self._dirty()
        return await self.raw.limit_create(s, plan_id=plan_id, symbol=symbol, side="SELL", qty=qty, price=price,
                                           client_id=client_id)

    # ── 조회 · 취소 (방향과 무관) ──
    async def cancel_cond(self, s, cond_id: str) -> None:
        self._dirty()
        await self.raw.cond_cancel(s, cond_id)

    async def cancel_limit(self, s, order_id: str) -> None:
        self._dirty()
        await self.raw.limit_cancel(s, order_id)

    async def cond_get(self, s, cond_id: str) -> Optional[dict]:
        return await self.raw.cond_get(s, cond_id)

    async def limit_get(self, s, order_id: str) -> Optional[dict]:
        return await self.raw.limit_get(s, order_id)

    async def cond_open_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        return await self.raw.cond_open_list(s, symbol)

    async def account_qty(self, s, plan_id: int, symbol: str) -> int:
        key = (plan_id, symbol)
        if self._tick_active and key in self._acct_cache:
            return self._acct_cache[key]
        v = await self.raw.account_qty(s, plan_id, symbol)
        if self._tick_active:
            self._acct_cache[key] = v
        return v

    async def limit_open_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        return await self.raw.limit_open_list(s, symbol)

    async def cond_closed_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        return await self.raw.cond_closed_list(s, symbol)

    async def limit_closed_list(self, s, symbol: Optional[str] = None) -> list[dict]:
        return await self.raw.limit_closed_list(s, symbol)

    def end_tick(self) -> None:
        """걸음이 끝나면 캐시를 끄고 비운다 (다시 맞추기 · 화면 요청이 걸음 캐시를 쓰지 않게)."""
        self._tick_active = False
        self._acct_cache = {}


def tick_of(price) -> Decimal:  # 편의
    return tick(price)
