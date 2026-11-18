"""1116-01 · 4차 검토 재현 시험 (가짜 브로커 · 가상 종목 · 실제 호출 0).

모든 시험은 끝에서 두 가지를 확인한다.
 1. 토스에 걸린 매도 합 <= 보유
 2. 보유 > 0 이면 (살아 있는 손절 수량 + 묶인 수량) = 보유
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.execution.plan import orderbook as ob
from backend.execution.plan import sizing, state
from backend.execution.plan.models import PlanFill, PlanLeg
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401
from backend.tests.test_plan_api import J, OK_ORIGIN, api, cookie, hdr, mk_plan  # noqa: F401
from backend.tests.test_plan_orderbook import (  # noqa: F401
    NOW, REG, ModifyThenFail, _api_line, _clean_env, _entry, cfg, legs_of, lines, setup)

D = Decimal


def live_sell_sum(raw):
    return sum(c["qty"] for c in raw.conds.values() if c["status"] == "WATCHING" and c["side"] == "SELL")


async def check_both(s, plan, raw, *, equal=True):
    held = raw.acct
    assert live_sell_sum(raw) <= held, f"토스 매도 합 {live_sell_sum(raw)} > 보유 {held}"
    if held > 0 and equal:
        live = sum(l.qty for l in await legs_of(s, plan))
        bound = (await ob.exposure(s, plan.id))["bound_new"]
        assert live + bound == held, f"손절 {live} + 묶음 {bound} != 보유 {held}"


# 막음 1 · 수정 결과 모름 + 옛 주문이 닫힘으로 읽힘 → 다시 걸지 않는다 (60 보유에 80 매도 방지)
async def test_unknown_modify_with_old_canceled_does_not_rehang(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        await eng._modify_leg(s, plan, leg, qty=leg.qty)
        eng.clock.advance(seconds=5)
        await eng.tick_plan(s, plan)
        assert leg.status == "CANCELED"                                              # 옛 주문은 닫힘으로 읽힘
        exp = await ob.exposure(s, plan.id)
        assert exp["bound_new"] == 20 and exp["unknown_modify"] == 0                # 새 줄을 묶인 수량으로 센다
        await check_both(s, plan, raw)
        eng.clock.advance(seconds=100)
        await eng.tick_plan(s, plan)
        await check_both(s, plan, raw)
        ln = (await lines(s, plan, state="needs_human"))[0]
        newid = [k for k, c in raw.conds.items() if c["client_id"] == ln.client_order_id][0]
        await ob.human_resolve(s, plan, ln.id, "open", toss_id=newid)
        assert leg.status == "WATCHING" and leg.toss_id == newid and leg.client_order_id == ln.client_order_id
        await eng.tick_plan(s, plan)
        await check_both(s, plan, raw)


# 높음 1 · 단건 조회가 빈 값인 다리 (수정 뒤) → 그 수량을 묶고 사람 확인 · 열려 있음으로 확정하면 다리가 살아남
async def test_on_missing_after_modify_binds_qty_and_human_open_aligns_leg(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        assert await eng._modify_leg(s, plan, leg, qty=leg.qty) is True
        raw.get_blind.add(leg.toss_id)
        raw.list_hidden_ids.add(leg.toss_id)
        await eng.sync_orders(s, plan)
        await eng.sync_orders(s, plan)                                    # 빈 조회는 연속 2걸음 뒤에 사람 확인
        ln = await ob.unresolved_lines(s, plan.id)
        assert len(ln) == 1 and leg.status == "UNCERTAIN"
        assert (await ob.exposure(s, plan.id))["bound_new"] == 20
        await eng.ensure_ladder(s, plan)
        assert plan.state == state.HALTED
        await check_both(s, plan, raw)
        await ob.human_resolve(s, plan, ln[0].id, "open", toss_id=leg.toss_id)
        assert leg.status == "WATCHING"
        await check_both(s, plan, raw)


# 높음 1 변형 · 수정 줄이 모름인 채 단건 조회까지 비어도 같은 다리의 수량을 두 번 묶지 않는다
async def test_missing_on_leg_with_unknown_modify_line_binds_once(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        old = leg.toss_id
        await eng._modify_leg(s, plan, leg, qty=leg.qty)                 # 옛 주문 살아 있음 + 새 줄 모름
        raw.get_blind.add(old)
        raw.list_hidden_ids.add(old)
        await eng.sync_orders(s, plan)
        await eng.sync_orders(s, plan)                                    # 빈 조회는 연속 2걸음 뒤에 사람 확인
        assert leg.status == "UNCERTAIN"
        assert (await ob.exposure(s, plan.id)) == {"bound_new": 20, "unknown_modify": 0}
        await eng.ensure_ladder(s, plan)
        assert live_sell_sum(raw) <= raw.acct + 20                        # 토스에는 옛 주문 + 새 주문이 같이 있을 수 있어 사람이 정한다
        assert sum(1 for c in raw.calls if c[0] == "cond_create") == 3     # 다시 걸지 않았다 (처음 3개뿐)


# 높음 2 · 수정 결과가 모를 때도 줄이기는 한다
async def test_unknown_modify_does_not_block_shrinking(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[-1]
        raw.fail_modify = 1
        await eng._modify_leg(s, plan, leg, qty=leg.qty)
        assert any(l.replaces_id for l in await ob.unresolved_lines(s, plan.id))
        s.add(PlanFill(plan_id=plan.id, side="SELL", qty=30, price=11, order_ref="tp-x", fill_seq=30))
        await s.flush()
        raw.acct = 30
        eng.clock.advance(seconds=5)
        assert await eng.ensure_ladder(s, plan) == "fixed"
        assert await sizing.plan_qty(s, plan) == 30
        assert live_sell_sum(raw) <= raw.acct
        assert leg.status == "WATCHING"                                   # 수정 중인 다리는 건드리지 않았다


# 높음 3 · 사람이 확정한 TP1 체결은 FILLED + 다음 걸음에 추적 전환 (TP1 을 다시 내지 않음)
async def test_human_confirmed_tp1_fill_moves_on_and_does_not_reissue(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12, "tp1_order": 12})
        await eng.ensure_ladder(s, plan)
        raw.create_no_id = True
        await eng.tick_plan(s, plan)
        raw.create_no_id = False
        eng.clock.advance(seconds=1)
        await eng.tick_plan(s, plan)
        ln = [l for l in await ob.unresolved_lines(s, plan.id) if l.role == "tp1"][0]
        for k, c in list(raw.conds.items()):
            if c["client_id"] == ln.client_order_id:
                raw.trigger(k, fill=True)
        raw.acct = 60 - ln.qty
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=ln.qty)
        tp1_leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "tp1"))).one()
        assert tp1_leg.status == "FILLED"
        await eng.resume_plan(s, plan)
        await eng.tick_plan(s, plan)
        assert plan.state == state.TP1_WAIT
        assert sum(1 for c in raw.calls if c[0] == "cond_create" and "tp1" in str(c[-1])) == 1     # TP1 은 한 번만
        await check_both(s, plan, raw, equal=False)


# 높음 4 · 기다리는 시간 안에 스위치를 껐다 켜도 두 번 사지 않는다
async def test_switch_toggle_during_wait_does_not_double_buy(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    sw = {"live": True, "paper": True}
    raw = FakeRaw("9.60")
    raw.acct = 0
    eng = make_engine(raw, regular=REG, clock=Clock(NOW), switches=lambda: sw)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan = await _entry(s, eng, raw)
        raw.limit_uncertain = False
        sw["live"] = False
        eng.clock.advance(seconds=5)
        await eng.tick_plan(s, plan)
        sw["live"] = True
        for _ in range(3):
            eng.clock.advance(seconds=5)
            await eng.tick_plan(s, plan)
        buys = [o for o in raw.limits.values() if o["side"] == "BUY"]
        assert len(buys) == 1                                              # 처음 낸 것뿐
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "buy"))).one()
        assert leg.status == "UNCERTAIN"                                   # 대조가 판정하기 전에는 CANCELED 로 두지 않는다
        await check_both(s, plan, raw)


# 높음 5 · 일부만 체결(3 < 6) 확정은 남은 주문을 앱에서 취소했다는 확인이 있어야 한다
async def test_partial_human_fill_requires_remainder_cancel_confirmation(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan = await _entry(s, eng, raw)
        raw.limit_uncertain = False
        eng.clock.advance(seconds=1)
        await eng.tick_plan(s, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        try:
            await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=3)
            raise AssertionError("확인 없이 일부 체결이 확정됨")
        except ob.ResolveError:
            pass
        assert (await s.get(type(ln), ln.id)).state == "needs_human"
        for o in raw.limits.values():
            o["status"] = "CANCELED"                                       # 대표가 앱에서 남은 주문을 취소했다
        raw.acct = 3
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=3, remainder_cancelled=True)
        for _ in range(3):
            await eng.tick_plan(s, plan)
        assert not [o for o in raw.limits.values() if o["status"] == "OPEN"]
        assert plan.state == state.HALTED                                  # 정지는 그대로 (재개는 사람이)
        assert sum(l.qty for l in await legs_of(s, plan)) == 3             # 체결 3주분 손절은 걸렸다
        await check_both(s, plan, raw)


async def test_partial_human_open_keeps_tracking_the_remainder(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan = await _entry(s, eng, raw)
        raw.limit_uncertain = False
        eng.clock.advance(seconds=1)
        await eng.tick_plan(s, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        oid = next(iter(raw.limits))
        raw.limits[oid].update(filled=3, remaining=3, avg=D("9.7"))
        raw.acct = 3
        await ob.human_resolve(s, plan, ln.id, "open", toss_id=oid, kind="limit")
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "buy"))).one()
        assert leg.status == "WATCHING" and leg.toss_id == oid            # 남은 주문을 계속 추적
        await eng.tick_plan(s, plan)
        assert await sizing.plan_qty(s, plan) == 3                        # 체결은 주문 상태에서 읽는다
        await check_both(s, plan, raw)


# 중간 1 · 조회가 비었고 닫힌 목록에 있으면 그 체결 수량을 장부에 적는다
async def test_on_missing_closed_list_records_the_fill(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.trigger(leg.toss_id, fill=True)
        raw.acct -= leg.qty
        raw.get_blind.add(leg.toss_id)
        await eng.sync_orders(s, plan)
        await eng.sync_orders(s, plan)                                    # 빈 조회는 연속 2걸음 뒤에 사람 확인
        assert leg.status == "FILLED"
        assert await sizing.plan_qty(s, plan) == 40
        await eng.ensure_ladder(s, plan)
        await check_both(s, plan, raw)


# 중간 2 · 접수된 매도의 조회가 비면 예약을 풀지 않고 사람 확인으로 보낸다
async def test_empty_lookup_of_reserved_sell_keeps_reservation_and_asks_human(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        resv = await eng._place_limit_sell_for_test(s, plan, 10) if hasattr(eng, "_place_limit_sell_for_test") else None
        if resv is None:
            from backend.execution.plan.models import PlanSellReservation
            resv = PlanSellReservation(plan_id=plan.id, kind="time_stop", qty=10, order_ref="L9", active=True, uncertain=False,
                                       order_price=9.0)
            s.add(resv)
            await s.flush()
        await eng.sync_orders(s, plan)
        await eng.sync_orders(s, plan)                                    # 빈 조회는 연속 2걸음 뒤에 사람 확인
        assert resv.active is True                                        # 풀지 않았다
        assert [l.role for l in await ob.unresolved_lines(s, plan.id)] == ["sell"]
        assert plan.state == state.HALTED


# 중간 4 · 목록 읽기 실패는 걸음 전체를 멈추지 않고 그 줄만 미룬다
async def test_list_read_failure_postpones_only_that_line(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        raw.create_no_id = True
        await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D(10)), "regular")
        raw.create_no_id = False
        raw.list_fail = True
        await eng.tick_plan(s, plan)                                       # 예외 없이 끝난다
        assert [l.state for l in await ob.unresolved_lines(s, plan.id)] == ["sent_unknown"]
        raw.list_fail = False
        await eng.tick_plan(s, plan)
        assert not [l for l in await ob.unresolved_lines(s, plan.id) if l.state == "sent_unknown"]


# 낮음 · 번호 모양 · 별도 확인 코드 동작 · 코드 사용 기록은 입력 오류로 되돌려지지 않는다
async def test_resolve_validates_toss_id_shape_and_keeps_code_used_on_input_error(api):
    plan = await mk_plan(api, "live")
    await _api_line(plan["id"], qty=6)
    cookie(api)
    lid = (await api.get(f"/api/v1/plans/{plan['id']}/unknown-orders")).json()["orders"][0]["id"]
    url = f"/api/v1/plans/{plan['id']}/unknown-orders/{lid}/resolve"
    r = await api.post(url, json={"decision": "open", "toss_id": "bad id;drop"}, headers=OK_ORIGIN)
    assert r.status_code == 422                                           # 영문 · 숫자 · - 만
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "resolve_order", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    cid, code = c.json()["challenge_id"], api.phone.code
    r = await api.post(url, json={"decision": "filled", "filled_qty": 9, "challenge_id": cid, "code": code}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "resolve"
    r = await api.post(url, json={"decision": "not_created", "challenge_id": cid, "code": code}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] != "resolve"      # 쓴 코드는 되살아나지 않는다
    c2 = await api.post("/api/v1/plans/confirm/challenge", json={"action": "resume", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    r = await api.post(url, json={"decision": "not_created", "challenge_id": c2.json()["challenge_id"], "code": api.phone.code},
                       headers=OK_ORIGIN)
    assert r.status_code == 400                                           # 정지 풀기 코드로는 확정할 수 없다
