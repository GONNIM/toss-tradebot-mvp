"""1116-01 · 계획 실행기 엔진 시험 (가짜 토스 · 가상 종목 TESTA · TESTB · 실제 호출 0)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.execution.plan import sizing, state
from backend.execution.plan.engine import params_of
from backend.execution.plan.models import Plan, PlanLeg, PlanLegPending, PlanSellReservation
from backend.execution.plan.pricing import D
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401

NOW = datetime(2026, 11, 20, 15, 0)
REG = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))


async def legs_of(s, plan, role="sl", status="WATCHING"):
    return list(await s.scalars(select(PlanLeg).where(
        PlanLeg.plan_id == plan.id, PlanLeg.role == role, PlanLeg.status == status).order_by(PlanLeg.seq)))


async def setup(price="10", qty=60, avg=10.0, regular=REG, **kw):
    raw = FakeRaw(price)
    raw.acct = qty
    eng = make_engine(raw, regular=regular, clock=Clock(NOW), **kw)
    return raw, eng


# ── 사다리 · 시간대 ─────────────────────────────────────────────

async def test_ladder_regular_three_legs_split_and_values(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        assert await eng.ensure_ladder(s, plan) == "fixed"
        legs = await legs_of(s, plan)
        assert [l.qty for l in legs] == [20, 20, 20]
        assert [D(l.watch_price) for l in legs] == [D("9.70"), D("9.50"), D("9.30")]
        assert [D(l.order_price) for l in legs] == [D("9.50"), D("9.31"), D("9.11")]   # 감시가 × 0.98 내림
        assert await eng.ensure_ladder(s, plan) == "ok"


async def test_ladder_off_hours_uses_emergency(plan_db):
    raw, eng = await setup(regular=None)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        assert [D(l.watch_price) for l in legs] == [D("8.50")] * 3
        assert [D(l.order_price) for l in legs] == [D("8.24")] * 3        # × 0.97 내림


async def test_remainder_goes_to_last_leg(plan_db):
    raw, eng = await setup(qty=62)
    async with get_session() as s:
        plan = await seed_holding(s, eng, qty=62)
        await eng.ensure_ladder(s, plan)
        assert [l.qty for l in await legs_of(s, plan)] == [20, 20, 22]


async def test_session_swap_modifies_three_legs_and_never_leaves_zero(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        eng.regular_window = lambda now: None            # 정규장 밖으로
        await eng._swap_session(s, plan, NOW)
        legs = await legs_of(s, plan)
        assert [D(l.watch_price) for l in legs] == [D("8.50")] * 3 and all(l.tag == "off" for l in legs)
        assert raw.count("cond_modify") == 3
        assert sum(l.qty for l in legs) == 60
        eng.regular_window = lambda now: REG             # 다시 정규장
        await eng._swap_session(s, plan, NOW)
        assert [D(l.watch_price) for l in await legs_of(s, plan)] == [D("9.70"), D("9.50"), D("9.30")]


async def test_gap_down_at_regular_open_sells_crossed_legs_immediately(plan_db):
    """갭 하락 뒤 정규장 전환: 비상 값 다리가 이미 현재가 위면 조건주문 0 · 즉시 지정가 · 다리를 먼저 줄임."""
    raw, eng = await setup(regular=None)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)                       # off: 감시가 8.50
        raw.price = D("8.00")
        eng.regular_window = lambda now: REG
        await eng._swap_session(s, plan, NOW)                  # 정규장 사다리 9.70 · 9.50 · 9.30 은 모두 현재가 위
        assert raw.count("limit_create") == 3
        assert [c[3] for c in raw.calls if c[0] == "limit_create"] == [D("7.84")] * 3   # 현재가 × 0.98 내림
        assert await legs_of(s, plan) == []                    # 다리는 먼저 줄었다
        assert await sizing.accepted_sell(s, plan.id) == 60
        # 줄이기(cond_cancel)가 매도(limit_create)보다 먼저
        kinds = [c[0] for c in raw.calls if c[0] in ("cond_cancel", "limit_create")]
        assert kinds.index("cond_cancel") < kinds.index("limit_create")


# ── 6-1 감시 방향 ──────────────────────────────────────────────

async def test_crossed_leg_at_registration_goes_to_limit_sell_and_reserves(plan_db):
    raw, eng = await setup(price="9.60")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        assert [l.seq for l in legs] == [2, 3]                  # 9.70 은 현재가 위 → 조건주문 아님
        sells = [c for c in raw.calls if c[0] == "limit_create"]
        assert len(sells) == 1 and sells[0][2:] == (20, D("9.40"))
        assert await sizing.accepted_sell(s, plan.id) == 20
        assert await eng.ensure_ladder(s, plan) == "ok"         # 불변식 A: 40 = 60 − 20


async def test_one_low_price_only_is_treated_as_anomaly(plan_db):
    """한쪽 시세만 낮으면 즉시 매도하지 않는다 · 옛 다리 그대로."""
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        first = legs[0]
        raw.price = D("9.60")
        raw.price_queue = [D("9.60"), D("9.60"), D("9.00")]     # 현재가 · 첫 확인 · 둘째 확인이 1% 넘게 다름
        ok = await eng._modify_leg(s, plan, first, vals=eng._values_for(plan, 1, "regular", D("9.60")))
        assert ok is False
        assert raw.count("limit_create") == 0
        assert first.status == "WATCHING" and first.toss_id in raw.conds and raw.conds[first.toss_id]["status"] == "WATCHING"


async def test_registration_response_recheck_cancels_flipped_leg(plan_db):
    """등록 응답 뒤 다시 읽었더니 방향이 뒤집힘 → 그 다리를 취소하고 즉시 지정가."""
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        raw.price_queue = [D("10"), D("9.60"), D("9.60"), D("9.60")]  # 현재가 · (등록) · 다시 읽기 · 확인...
        leg = await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D("10")), "regular")
        assert leg is None
        assert raw.count("cond_create") == 1 and raw.count("cond_cancel") == 1
        assert raw.count("limit_create") == 1


async def test_sell_reject_replaces_leg_with_passing_value_then_halts_after_three(plan_db):
    raw, eng = await setup(price="9.60")
    raw.reject_sell = "price-out-of-range"
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)                         # seq1 즉시 매도 거절 → 비상 값으로 다시 건다
        legs = await legs_of(s, plan)
        assert sorted(l.seq for l in legs) == [1, 2, 3]
        e1 = [l for l in legs if l.seq == 1][0]
        assert D(e1.watch_price) == D("8.16") and e1.tag == "emergency"      # 현재가 × 0.85 올림
        assert await sizing.accepted_sell(s, plan.id) == 0       # 거절된 예약은 풀림
        for _ in range(2):                                       # 같은 다리에서 거절 · 다시 걸기가 되풀이
            await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        assert plan.state == state.HALTED
        assert any(a[0] == "critical" for a in eng._alerts)


async def test_reject_counter_resets_after_normal_registration(plan_db):
    raw, eng = await setup(price="9.60")
    raw.reject_sell = "x"
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        assert params_of(plan)["reject_loops"]["1"] == 1
        leg = (await legs_of(s, plan))[0]
        raw.price = D("10")
        assert await eng._modify_leg(s, plan, leg, vals=eng._values_for(plan, 1, "regular", D("10")))
        assert "1" not in (params_of(plan).get("reject_loops") or {})      # 초기화


async def test_pending_buy_is_cancelled_before_plan_sell(plan_db):
    raw, eng = await setup(price="9.60")
    async with get_session() as s:
        plan = await seed_holding(s, eng, state_=state.HOLDING)
        s.add(PlanLeg(plan_id=plan.id, role="buy", seq=1, kind="limit", side="BUY", toss_id="LBUY", qty=6,
                      status="WATCHING"))
        raw.limits["LBUY"] = dict(status="OPEN", symbol="TESTA", side="BUY", qty=6, price=D("9"), filled=0, remaining=6, avg=None)
        await s.flush()
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        kinds = [c[0] for c in raw.calls]
        assert kinds.index("limit_cancel") < kinds.index("limit_create")


async def test_sell_not_possible_in_session_keeps_old_leg_and_alerts(plan_db):
    raw, eng = await setup(price="10", limit_factor=None)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.price = D("9.60")
        ok = await eng._modify_leg(s, plan, leg, vals=eng._values_for(plan, 1, "regular", D("9.60")))
        assert ok is False and leg.status == "WATCHING" and raw.count("limit_create") == 0
        assert any(a[0] == "critical" for a in eng._alerts)


# ── 불변식 5절 ─────────────────────────────────────────────────

async def test_triggered_leg_counts_as_reservation_and_ledger_stays_balanced(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg1 = (await legs_of(s, plan))[0]
        raw.trigger(leg1.toss_id, fill=False)                    # 발동 · 아직 미체결
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20
        assert await eng.ensure_ladder(s, plan) == "ok"          # 손절 합 40 = 60 − 20
        raw.trigger(leg1.toss_id, fill=True)
        raw.acct = 40
        await eng.sync_orders(s, plan)
        assert await sizing.plan_qty(s, plan) == 40 and await sizing.accepted_sell(s, plan.id) == 0
        assert await eng.ensure_ladder(s, plan) == "ok"


async def test_unfired_tp1_is_not_a_reservation(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        await eng._tp1_step(s, plan, True)
        tp1 = await legs_of(s, plan, role="tp1")
        assert len(tp1) == 1 and tp1[0].qty == 30                 # 불변식 B: ½ 내림
        assert await sizing.accepted_sell(s, plan.id) == 0


async def test_shortage_re_registers_missing_qty_and_alerts(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[1]
        leg.status = "EXPIRED"                                   # 만료 = 모자람
        await s.flush()
        assert await eng.ensure_ladder(s, plan) == "fixed"
        assert sum(l.qty for l in await legs_of(s, plan)) == 60
        assert any(a[1] == "손절 다리 모자람" for a in eng._alerts)


async def test_shortage_protective_legs_are_re_hung_even_when_halted(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        for l in await legs_of(s, plan):
            l.status = "CANCELED"
        await state.halt(s, plan, "시험")
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED
        assert sum(l.qty for l in await legs_of(s, plan)) == 60


async def test_normal_excess_after_accept_is_shrunk_without_halt(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        await sizing.reserve(s, plan.id, "triggered", 20, "T1")  # 발동 직후 접수 수량이 늘었다
        assert await eng.ensure_ladder(s, plan) == "fixed"
        assert plan.state == state.HOLDING
        assert sum(l.qty for l in await legs_of(s, plan)) == 40


async def test_duplicate_pair_halts(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        s.add(PlanLeg(plan_id=plan.id, role="sl", seq=1, kind="cond", toss_id="DUP", qty=20, watch_price=9.0,
                      order_price=8.9, status="WATCHING"))
        await s.flush()
        assert await eng.ensure_ladder(s, plan) == "halted"
        assert plan.state == state.HALTED and len(legs) == 3


async def test_account_less_than_plan_qty_shrinks_base(plan_db):
    raw, eng = await setup(qty=45)                               # 계좌 보유가 더 적다
    async with get_session() as s:
        plan = await seed_holding(s, eng, qty=60)
        await eng.ensure_ladder(s, plan)
        assert sum(l.qty for l in await legs_of(s, plan)) == 45


async def test_outside_holding_forces_tp1_watch_mode(plan_db):
    raw, eng = await setup(qty=70)                               # 계좌 70 > 계획 60 · 계획 밖 보유 10
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        before = raw.count("cond_create")
        await eng._tp1_step(s, plan, True)
        assert raw.count("cond_create") == before and await legs_of(s, plan, role="tp1") == []
        raw.price = D("12.00")                                   # TP1 에 닿음 → 감시 모드 지정가
        await eng._tp1_step(s, plan, True)
        assert raw.count("limit_create") == 1
        kinds = [c[0] for c in raw.calls]
        assert kinds.index("cond_cancel") < kinds.index("limit_create") or raw.count("cond_modify") > 0
        assert await sizing.accepted_sell(s, plan.id) == 30


async def test_tp1_registration_rejected_falls_back_to_watch_mode(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        raw.reject_cond_code, raw.reject_cond_sides = "sellable-quantity-exceeded", ("SELL",)
        await eng._tp1_step(s, plan, True)                       # U1 거절 → 감시 모드 (현재가가 아직 TP1 아래라 대기)
        assert await legs_of(s, plan, role="tp1") == [] and raw.count("limit_create") == 0


async def test_tp1_already_crossed_goes_to_immediate_limit(plan_db):
    raw, eng = await setup(price="12.50")
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        await eng._tp1_step(s, plan, True)
        assert raw.count("limit_create") == 1 and await legs_of(s, plan, role="tp1") == []


# ── 추적 · 익절 뒤 ──────────────────────────────────────────────

class CountingRaw(FakeRaw):
    """수정 시작 순간의 다른 손절 다리 수를 기록한다 (손절 0건인 순간이 없는지)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.snap: list[tuple[int, int]] = []

    async def cond_modify(self, s, cond_id, **kw):
        live = [c for c in self.conds.values() if c["status"] == "WATCHING" and c["side"] == "SELL" and c["id"] != cond_id]
        self.snap.append((len(live), sum(c["qty"] for c in live)))
        return await super().cond_modify(s, cond_id, **kw)


@pytest.mark.parametrize("fail_first", [False, True])    # U1 허용 · 거절 두 순서 모두 같은 절차
async def test_trail_conversion_keeps_three_legs_and_never_zero(plan_db, fail_first):
    raw = CountingRaw("13")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        plan.peak_price = 14.0
        await eng.ensure_ladder(s, plan)
        if fail_first:
            raw.price = D("11")
            raw.reject_cond_code, raw.reject_cond_sides = "x", ("SELL",)
            await eng._tp1_step(s, plan, True)               # U1 거절 → 감시 모드 (등록 모드 TP1 없음)
            raw.reject_cond_code = None
            raw.price = D("13")
        # TP1 30주 체결 (남은 30)
        s.add(PlanLeg(plan_id=plan.id, role="tp1", seq=1, kind="cond", toss_id="TP", qty=30, watch_price=12.0,
                      order_price=12.0, status="WATCHING"))
        raw.conds["TP"] = dict(id="TP", status="FILLED", symbol="TESTA", side="SELL", qty=30, watch=D(12), order=D(12),
                               client_id="", order_id=None, filled=30, remaining=0, avg=D(12))
        raw.acct = 30
        await s.flush()
        raw.snap.clear()
        await eng.tick_plan(s, plan)
        assert plan.state == state.TRAILING
        legs = await legs_of(s, plan)
        assert len(legs) == 3 and sum(l.qty for l in legs) == 30
        assert {D(l.watch_price) for l in legs} == {D("11.90")}          # max(평단 10, 고점 14 × 0.85)
        assert raw.snap and all(n >= 2 and q >= 1 for n, q in raw.snap)   # 한 건 수정 중 다른 건이 걸려 있음


async def test_tp1_then_drop_below_average_waits(plan_db):
    """익절 뒤 평단 아래로 하락 → 익절 뒤 대기 · 다리 남음."""
    raw, eng = await setup(price="9.80")
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        plan.peak_price = 11.0                               # max(10, 9.35) = 10.00 → 현재가 9.80 아래 아님
        await eng.ensure_ladder(s, plan)
        s.add(PlanLeg(plan_id=plan.id, role="tp1", seq=1, kind="cond", toss_id="TP", qty=30, watch_price=12.0,
                      order_price=12.0, status="WATCHING"))
        raw.conds["TP"] = dict(id="TP", status="FILLED", symbol="TESTA", side="SELL", qty=30, watch=D(12), order=D(12),
                               client_id="", order_id=None, filled=30, remaining=0, avg=D(12))
        raw.acct = 30
        await s.flush()
        await eng.tick_plan(s, plan)
        assert plan.state == state.TP1_WAIT
        legs = await legs_of(s, plan)
        assert legs and sum(l.qty for l in legs) == 30


async def test_trail_raise_only_up_and_min_step(plan_db):
    raw, eng = await setup(price="14")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        plan.state, plan.peak_price = state.TRAILING, 14.0
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        assert {D(l.watch_price) for l in legs} == {D("11.90")}
        before = raw.count("cond_modify")
        await eng._trail_step(s, plan, NOW)                  # 고점 그대로 → 올릴 것 없음
        assert raw.count("cond_modify") == before
        raw.price = D("16")                                  # 고점 갱신 (10% 안쪽 아님 → 보류)
        await eng._trail_step(s, plan, NOW)
        assert plan.pending_peak == 16.0 and plan.peak_price == 14.0
        raw.price = D("15.5")
        await eng._trail_step(s, plan, NOW)                  # 15.5 는 보류 값 16 의 3% 안 → 16 확정 안 됨 (|15.5−16|/16 = 3.1%)
        assert plan.peak_price in (14.0, 15.5)


# ── 시간 손절 ──────────────────────────────────────────────────

async def _timestop_plan(s, eng):
    plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-09T22:00:00"})
    await eng.ensure_ladder(s, plan)
    return plan


async def test_timestop_lift_one_session_then_clean_then_cancel_back_to_emergency(plan_db):
    raw = CountingRaw("10.50")
    raw.acct = 60
    clock = Clock(datetime(2026, 11, 20, 15, 0))               # 정규장 시작 14:30 + 30분 = 끌어올리기 시작
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await _timestop_plan(s, eng)
        raw.snap.clear()
        await eng._timestop_step(s, plan, clock())
        legs = await legs_of(s, plan)
        assert {D(l.watch_price) for l in legs} == {D("10.40")}      # min(10.50×0.99 올림, 현재가 − 2틱)
        assert len(legs) == 3 and all(n >= 2 for n, _ in raw.snap)   # 손절 0건인 순간 없음
        before = raw.count("cond_modify")
        clock.advance(minutes=5)
        await eng._timestop_step(s, plan, clock())
        assert raw.count("cond_modify") == before                    # 15분마다 · 5분 뒤는 다시 하지 않음
        # 정리: 종료 30분 전부터 1건씩 지정가 매도
        clock.t = datetime(2026, 11, 20, 20, 31)
        await eng._timestop_step(s, plan, clock())
        assert raw.count("limit_create") == 1 and len(await legs_of(s, plan)) == 2
        await eng._timestop_step(s, plan, clock())
        assert raw.count("limit_create") == 2
        assert await sizing.accepted_sell(s, plan.id) == 40
        # 종료 1분 전: 체결 안 된 매도 취소 · 그 수량은 비상 값 다리로 되돌림 (총량 = 기준 − 접수)
        clock.t = datetime(2026, 11, 20, 20, 59)
        await eng._timestop_step(s, plan, clock())
        assert await sizing.accepted_sell(s, plan.id) == 0
        legs = await legs_of(s, plan)
        assert sum(l.qty for l in legs) == 60
        assert plan.timestop_stage == "clean"


async def test_timestop_not_before_due_and_not_when_halted(plan_db):
    raw, eng = await setup(price="10.50")
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-19T22:00:00"})   # 5거래일 안
        await eng.ensure_ladder(s, plan)
        await eng._timestop_step(s, plan, NOW)
        assert raw.count("cond_modify") == 0
        plan2 = await seed_holding(s, eng, symbol="TESTB", extra={"announce_at": "2026-11-09T22:00:00"})
        await eng.ensure_ladder(s, plan2)
        await state.halt(s, plan2, "시험")
        await eng._timestop_step(s, plan2, NOW)                    # HALTED 에서는 단계 진행이 멈춘다
        assert plan2.timestop_stage == "none"


async def test_stale_sell_reprice_after_10_seconds_then_release_after_second_failure(plan_db):
    raw = FakeRaw("10.50")
    raw.acct = 60
    clock = Clock(NOW)
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("10.50"), kind="time_stop", old_leg=leg)
        r = (await s.scalars(select(PlanSellReservation).where(PlanSellReservation.kind == "time_stop"))).first()
        assert D(r.order_price) == D("10.29")
        raw.price = D("10.00")                                       # 주문가 아래로 내려감
        await eng._reprice_stale(s, plan, clock())
        assert r.below_since is not None and raw.count("limit_create") == 1
        clock.advance(seconds=11)
        await eng._reprice_stale(s, plan, clock())                   # 10초 지나 취소 · 현재가 × 0.95 로 다시
        assert raw.count("limit_cancel") == 1
        sells = [c for c in raw.calls if c[0] == "limit_create"]
        assert sells[-1][3] == D("9.50")
        new = (await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.kind == "time_stop", PlanSellReservation.active.is_(True)))).first()
        assert new.retries == 1
        raw.price = D("9.00")
        clock.advance(seconds=1)
        await eng._reprice_stale(s, plan, clock())
        clock.advance(seconds=11)
        await eng._reprice_stale(s, plan, clock())                   # 두 번째도 실패 → 예약 풀고 보호 다리 · ⑨ 긴급
        left = list(await s.scalars(select(PlanSellReservation).where(
            PlanSellReservation.kind == "time_stop", PlanSellReservation.active.is_(True))))
        assert left == []                                            # 시간 손절 예약은 풀렸다 (다리는 6-1 로 다시 걸림)
        assert any(a[0] == "critical" and a[1] == "다시 내기 실패" for a in eng._alerts)


async def test_timestop_stop_restores_session_values(plan_db):
    raw = FakeRaw("10.50")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await _timestop_plan(s, eng)
        await eng._timestop_step(s, plan, NOW)
        await eng.stop_timestop(s, plan)
        assert plan.timestop_stage == "stopped"
        assert [D(l.watch_price) for l in await legs_of(s, plan)] == [D("9.70"), D("9.50"), D("9.30")]


# ── 오류 · 정지 · Kill Switch ─────────────────────────────────────

async def test_three_modify_errors_halt(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.fail_modify = 3
        for _ in range(3):
            assert await eng._modify_leg(s, plan, leg, qty=10) is False
        assert plan.state == state.HALTED
        assert (await s.scalars(select(PlanLegPending).where(PlanLegPending.leg_id == leg.id))).first() is not None


async def test_stop_plan_keeps_sell_legs(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        await eng.stop_plan(s, plan)
        assert plan.state == state.HALTED and len(await legs_of(s, plan)) == 3
        assert raw.count("cond_cancel") == 0


async def test_kill_switch_sell_stop_cancels_all_and_halts(plan_db):
    raw, eng = await setup(kill=(True, False))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        # 다리를 먼저 걸어 둔다 (kill 상태는 tick 에서만 본다)
        eng.kill_state = lambda: (False, True)
        await eng.ensure_ladder(s, plan)
        eng.kill_state = lambda: (True, False)
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED and await legs_of(s, plan) == []
        assert raw.count("cond_cancel") == 3


async def test_kill_switch_new_entry_blocked(plan_db):
    raw, eng = await setup(kill=(True, True))
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        assert await eng.start_entry(s, plan) is False and raw.count("cond_create") == 0


async def test_live_switch_off_blocks_entry_and_cancels_buys_then_alerts_on_failure(plan_db, monkeypatch):
    sw = {"live": True, "paper": True}
    raw, eng = await setup(switches=lambda: sw)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        assert await eng.start_entry(s, plan) is True
        assert raw.count("cond_create") == 1 and plan.state == state.ENTRY_ARMED
        sw["live"] = False
        await eng.tick_plan(s, plan)                                  # 꺼짐 → 대기 매수 조건주문 취소
        assert raw.count("cond_cancel") == 1
        # 취소 실패 → 3초 뒤 1번 더 → ⑨ 긴급
        raw.conds[list(raw.conds)[0]]["status"] = "WATCHING"
        leg = (await legs_of(s, plan, role="buy", status="CANCELED"))[0]
        leg.status = "WATCHING"
        raw.cancel_fail = True
        monkeypatch.setattr(asyncio, "sleep", lambda *_: _noop_coro())
        assert await eng.cancel_buys_on_switch_off(s, plan) is False
        assert any(a[0] == "critical" for a in eng._alerts)
        raw.cancel_fail = False


async def _noop_coro():
    return None


async def test_switch_off_keeps_sell_side_running(plan_db):
    sw = {"live": False, "paper": False}
    raw, eng = await setup(switches=lambda: sw)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.tick_plan(s, plan)                                   # 꺼져 있어도 체결 뒤 다리 등록은 계속
        assert len(await legs_of(s, plan)) == 3


async def test_approved_plan_waits_when_live_off_and_does_not_order(plan_db):
    sw = {"live": False, "paper": False}
    raw, eng = await setup(switches=lambda: sw)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        await eng.tick_plan(s, plan)
        assert plan.state == state.APPROVED and raw.calls == []


# ── 계획 만들기 · 승인 ───────────────────────────────────────────

async def test_draft_edit_bumps_revision_and_non_draft_is_rejected(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        h1, r1 = plan.content_hash, plan.revision
        await eng.update_draft(s, plan, {"qty": 12})
        assert plan.revision == r1 + 1 and plan.content_hash != h1
        await eng.update_draft(s, plan, {"qty": 12})                   # 같은 값 → 판 그대로
        assert plan.revision == r1 + 1
        plan.state = state.APPROVED
        with pytest.raises(state.TransitionError):
            await eng.update_draft(s, plan, {"qty": 18})


async def test_approval_rules_aside_caps_and_one_open_plan_per_symbol(plan_db, monkeypatch):
    raw, eng = await setup()
    async with get_session() as s:
        live = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        with pytest.raises(state.TransitionError):
            await eng.approve(s, live, by="Aside(대표 지시)")           # 실전은 대표만
        with pytest.raises(state.TransitionError, match="상한"):
            await eng.approve(s, live, by="대표")                      # 상한 기본값 0 = 주문 불가
        monkeypatch.setenv("PLAN_MAX_ORDER_USD", "1000")
        monkeypatch.setenv("PLAN_TOTAL_CAP_USD", "2000")
        await eng.approve(s, live, by="대표")
        assert live.state == state.APPROVED
        with pytest.raises(state.TransitionError):
            await eng.create_draft(s, symbol="TESTA", mode="paper", params={"qty": 6})   # 같은 종목 두 번째 거부
        paper = await eng.create_draft(s, symbol="TESTB", mode="paper", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        await eng.approve(s, paper, by="Aside(대표 지시)")             # 모의는 Aside 도 가능
        assert paper.state == state.APPROVED


async def test_cap_total_blocks_second_live_plan(plan_db, monkeypatch):
    monkeypatch.setenv("PLAN_MAX_ORDER_USD", "130")
    monkeypatch.setenv("PLAN_TOTAL_CAP_USD", "150")
    raw, eng = await setup()
    async with get_session() as s:
        a = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 10, "buy_order": 10, "qty": 6})
        await eng.approve(s, a, by="대표")
        b = await eng.create_draft(s, symbol="TESTB", mode="live", params={"buy_watch": 10, "buy_order": 10, "qty": 12})
        with pytest.raises(state.TransitionError, match="합계"):
            await eng.approve(s, b, by="대표")


async def test_buy_prices_floor_and_one_buy_at_a_time(plan_db):
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live",
                                      params={"buy_watch": 9.456, "buy_order": 9.459, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        c = [x for x in raw.calls if x[0] == "cond_create"][0]
        assert c[3] == D("9.45") and c[4] == D("9.45")                 # 감시가 · 주문가 모두 내림
        await eng._place_buy(s, plan)
        assert raw.count("cond_create") == 1                           # 매수 주문은 계획당 동시에 1개


async def test_buy_already_below_goes_to_plain_limit(plan_db):
    raw, eng = await setup(price="9.00")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        assert raw.count("cond_create") == 0 and raw.count("limit_create") == 1


async def test_entry_fill_moves_to_holding_and_registers_ladder(plan_db):
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live",
                                      params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 60, "ladder_pcts": [0.03, 0.05, 0.07]})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        cid = [k for k, c in raw.conds.items() if c["side"] == "BUY"][0]
        raw.trigger(cid, fill=True)
        raw.acct = 60
        await eng.tick_plan(s, plan)
        assert plan.state == state.HOLDING and plan.avg_price == 9.5
        assert len(await legs_of(s, plan)) == 3


# ── 보유 인수 ────────────────────────────────────────────────────

async def test_adopt_waits_for_foreign_conds_notifies_once_after_10_minutes(plan_db):
    raw = FakeRaw("10")
    raw.acct = 30
    clock = Clock(NOW)
    eng = make_engine(raw, regular=REG, clock=clock)
    raw.conds["F1"] = dict(id="F1", status="WATCHING", symbol="TESTA", side="SELL", qty=30, watch=D("9"), order=D("8.9"),
                           client_id="app", order_id=None, filled=0, remaining=30, avg=None)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", source="adopt",
                                      params={"adopt": {"qty": 30, "avg_price": 10.0}, "ladder_pcts": [0.03, 0.05, 0.07]})
        await eng.approve(s, plan, by="대표") if False else None
        plan.state = state.APPROVED
        plan.approved_at = clock()
        await eng.adopt_approve(s, plan)
        assert plan.state == state.ADOPT_PENDING
        await eng.tick_plan(s, plan)
        assert plan.state == state.ADOPT_PENDING and not plan.adopt_notified
        clock.advance(minutes=11)
        await eng.tick_plan(s, plan)
        await eng.tick_plan(s, plan)
        assert plan.adopt_notified and len([a for a in eng._alerts if a[1] == "인수 대기 중"]) == 1   # 대기 유지 + ⑨ 1번
        assert plan.state == state.ADOPT_PENDING
        raw.conds["F1"]["status"] = "CANCELED"                         # 앱 조건주문을 지움 → 다음 확인에서 등록
        await eng.tick_plan(s, plan)
        assert plan.state == state.HOLDING and sum(l.qty for l in await legs_of(s, plan)) == 30


async def test_adopt_requires_live_switch(plan_db):
    sw = {"live": False, "paper": False}
    raw, eng = await setup(switches=lambda: sw)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", source="adopt", params={"adopt": {"qty": 30}})
        plan.state = state.APPROVED
        with pytest.raises(state.TransitionError):
            await eng.adopt_approve(s, plan)


# ── 모의 · 모의는 토스 주문 API 를 부르지 않는다 ─────────────────────

class _ExplodingToss:
    def __getattr__(self, name):
        raise AssertionError(f"모의 계획이 토스를 불렀습니다: {name}")


async def test_paper_full_flow_never_touches_toss_and_follows_gap_rule(plan_db):
    from backend.execution.plan.brokers import DirectionGate, PaperRaw
    from backend.execution.plan.engine import PlanEngine
    from backend.execution.plan.models import PlanPaperOrder

    price = {"v": D("10")}

    async def px(symbol):
        return price["v"]

    toss = _ExplodingToss()                                            # 부르면 시험 실패
    raw = PaperRaw(px)
    alerts: list = []

    async def notify(level, title, body, category):
        alerts.append((level, title, body, category))

    eng = PlanEngine(DirectionGate(raw), notify=notify, clock=Clock(NOW), regular_window=lambda n: REG,
                     switches=lambda: {"live": False, "paper": True})
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper",
                                      params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 60, "ladder_pcts": [0.03, 0.05, 0.07]})
        await eng.approve(s, plan, by="Aside(대표 지시)")
        await eng.tick_plan(s, plan)
        assert plan.state == state.ENTRY_ARMED
        price["v"] = D("9.50")
        await raw.on_price(s, "TESTA", price["v"])
        await eng.tick_plan(s, plan)
        assert plan.state == state.HOLDING and plan.avg_price == 9.5
        legs = await legs_of(s, plan)
        assert [D(l.watch_price) for l in legs] == [D("9.22"), D("9.03"), D("8.84")]
        price["v"] = D("9.00")                                          # 갭으로 1번 주문가(9.03)를 건너뜀
        await raw.on_price(s, "TESTA", price["v"])
        await eng.tick_plan(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20              # 1번은 발동 · 접수 · 주문가를 건너뛰어 미체결
        assert await sizing.plan_qty(s, plan) == 40                      # 2번(주문가 8.84)은 가격이 닿아 체결
        price["v"] = D("9.05")                                           # 주문가에 닿음
        await raw.on_price(s, "TESTA", price["v"])
        await eng.tick_plan(s, plan)
        assert await sizing.plan_qty(s, plan) == 20                      # 가격이 1번 주문가(9.03)에 닿아 체결
        assert all(a[3] == "system" and "[모의 시험]" in a[1] for a in alerts)   # 모의 알림은 시스템 범주 · 표시
