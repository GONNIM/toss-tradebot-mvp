"""수량 불변식 · 매도 예약 장부 · 계획서 5절.

용어
- plan_qty: 이 계획 매수 체결 합 − 이 계획 매도 체결 합 (인수 계획은 인수 수량에서 시작).
- base: min(plan_qty, 계좌 보유) = 다리 기준 수량.
- accepted_sell: 토스에 실제 접수된 매도 주문의 남은 수량 합 (발동된 조건주문 · TP1 감시 모드 지정가 · 시간 손절 지정가).
  발동 전 TP1 조건주문은 예약이 아니다.
- 불변식 A: 대기 중 손절 다리 수량 합 = base − accepted_sell.
- 불변식 B: TP1 조건주문(등록 모드) 수량 ≤ (base − accepted_sell) 의 ½ 내림.
- 불변식 C: 계좌 보유 > plan_qty 면 TP1 등록 모드를 쓰지 않고 TP1 감시 모드로 강제.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select

from .models import Plan, PlanFill, PlanLeg, PlanSellReservation

# 열린(= 같은 종목에 두 번째를 막는) 계획 상태 (6-2)
OPEN_STATES = (
    "APPROVED", "ENTRY_ARMED", "ENTRY_RETRY", "HOLDING", "TP1_WAIT", "TRAILING", "ADOPT_PENDING", "HALTED",
)
# 손절 다리 (대기 중)
SL_LIVE = ("WATCHING",)


def compute_base(plan_qty: int, account_qty: int) -> int:
    return max(0, min(plan_qty, account_qty))


def split_ladder(total: int, n: int = 3) -> list[int]:
    """사다리 수량 = total 을 n 으로 나눠 내림 · 나머지는 마지막 단계 (5절 9항). 0 인 단계는 만들지 않는다."""
    if total <= 0:
        return []
    each = total // n
    parts = [each] * (n - 1) + [total - each * (n - 1)]
    return [q for q in parts if q > 0]


def sl_target(base: int, accepted_sell: int) -> int:
    """불변식 A 의 손절 다리 합 목표."""
    return max(0, base - max(0, accepted_sell))


def tp1_cap(base: int, accepted_sell: int) -> int:
    """불변식 B."""
    return max(0, (base - max(0, accepted_sell)) // 2)


def must_use_tp1_watch(account_qty: int, plan_qty: int) -> bool:
    """불변식 C · 계획 밖 보유가 있으면 TP1 감시 모드 강제."""
    return account_qty > plan_qty


def exposure_over(confirmed_sum: int, unknown_new: int, target: int) -> bool:
    """수정하다 결과를 모르는 줄이 있을 때의 넘침 검사 · 확인된 다리와 새 줄을 둘 다 세어 목표를 넘는가.
    (보호 수량에는 확인된 것만 센다 · 이 함수는 넘침 가능성만 본다)"""
    return confirmed_sum + unknown_new > target


@dataclass(frozen=True)
class InvariantReport:
    status: str          # ok | shortage | excess
    delta: int           # shortage 면 모자란 수량 · excess 면 넘친 수량
    sl_sum: int
    target: int
    tp1_ok: bool
    legs_per_seq_dup: bool = False   # 짝이 여럿 (같은 seq 의 대기 다리가 둘 이상)


def check_invariants(*, base: int, accepted_sell: int, sl_qtys: list[int], tp1_qty: int = 0,
                     dup_pairs: bool = False) -> InvariantReport:
    target = sl_target(base, accepted_sell)
    s = sum(sl_qtys)
    if dup_pairs or s > target:
        status, delta = "excess", max(s - target, 0)
    elif s < target:
        status, delta = "shortage", target - s
    else:
        status, delta = "ok", 0
    return InvariantReport(status, delta, s, target, tp1_qty <= tp1_cap(base, accepted_sell), dup_pairs)


# ─── DB 읽기 ────────────────────────────────────────────────────

async def plan_qty(session, plan: Plan) -> int:
    buys = await session.scalar(
        select(func.coalesce(func.sum(PlanFill.qty), 0)).where(PlanFill.plan_id == plan.id, PlanFill.side == "BUY"))
    sells = await session.scalar(
        select(func.coalesce(func.sum(PlanFill.qty), 0)).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL"))
    return int(plan.plan_qty_hint or 0) + int(buys or 0) - int(sells or 0)


async def accepted_sell(session, plan_id: int) -> int:
    n = await session.scalar(
        select(func.coalesce(func.sum(PlanSellReservation.qty), 0)).where(
            PlanSellReservation.plan_id == plan_id, PlanSellReservation.active.is_(True)))
    return int(n or 0)


async def live_sl_legs(session, plan_id: int) -> list[PlanLeg]:
    rows = await session.scalars(
        select(PlanLeg).where(PlanLeg.plan_id == plan_id, PlanLeg.role == "sl", PlanLeg.status == "WATCHING")
        .order_by(PlanLeg.seq, PlanLeg.id))
    return list(rows)


async def live_tp1_leg(session, plan_id: int) -> Optional[PlanLeg]:
    return await session.scalar(
        select(PlanLeg).where(PlanLeg.plan_id == plan_id, PlanLeg.role == "tp1", PlanLeg.status == "WATCHING"))


async def reserve(session, plan_id: int, kind: str, qty: int, order_ref: Optional[str]) -> PlanSellReservation:
    row = PlanSellReservation(plan_id=plan_id, kind=kind, qty=int(qty), order_ref=order_ref, active=True)
    session.add(row)
    await session.flush()
    return row


async def release(session, plan_id: int, order_ref: str) -> int:
    """그 주문의 예약을 푼다 · 풀린 수량을 돌려준다."""
    rows = await session.scalars(
        select(PlanSellReservation).where(
            PlanSellReservation.plan_id == plan_id, PlanSellReservation.order_ref == order_ref,
            PlanSellReservation.active.is_(True)))
    n = 0
    for r in rows:
        r.active = False
        n += r.qty
    await session.flush()
    return n


async def open_plan_exists(session, symbol: str, exclude_id: Optional[int] = None) -> bool:
    q = select(func.count()).select_from(Plan).where(Plan.symbol == symbol, Plan.state.in_(OPEN_STATES))
    if exclude_id is not None:
        q = q.where(Plan.id != exclude_id)
    return int(await session.scalar(q) or 0) > 0
