"""1116-01 · 주문 장부 · 결과 모르는 주문 대조 시험 (Fable 재설계 막음 조건 · 가짜 브로커 · 가상 종목 · 실제 호출 0)."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.execution.exceptions import ExecutionError
from backend.execution.plan import orderbook as ob
from backend.execution.plan import sizing, state
from backend.execution.plan.engine import runtime_of
from backend.execution.plan.models import Plan, PlanFill, PlanLeg, PlanOrderBook, PlanSellReservation
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401
from backend.tests.test_plan_api import J, OK_ORIGIN, PARAMS, TOKEN, api, cookie, hdr, mk_plan  # noqa: F401

D = Decimal
NOW = datetime(2026, 11, 20, 15, 0)
REG = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))
ENV = ("PLAN_ORDER_SETTLE_SEC", "PLAN_ORDER_LIST_SEARCHABLE", "PLAN_ORDER_LIST_PAGING_KNOWN")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)


def cfg(monkeypatch, *, settle=0, searchable=False, paging=False):
    monkeypatch.setenv("PLAN_ORDER_SETTLE_SEC", str(settle))
    monkeypatch.setenv("PLAN_ORDER_LIST_SEARCHABLE", "1" if searchable else "0")
    monkeypatch.setenv("PLAN_ORDER_LIST_PAGING_KNOWN", "1" if paging else "0")


async def legs_of(s, plan, role="sl", status="WATCHING"):
    return list(await s.scalars(select(PlanLeg).where(
        PlanLeg.plan_id == plan.id, PlanLeg.role == role, PlanLeg.status == status).order_by(PlanLeg.seq)))


async def lines(s, plan, **kw):
    q = select(PlanOrderBook).where(PlanOrderBook.plan_id == plan.id)
    for k, v in kw.items():
        q = q.where(getattr(PlanOrderBook, k) == v)
    return list(await s.scalars(q.order_by(PlanOrderBook.id)))


async def setup(price="10", qty=60):
    raw = FakeRaw(price)
    raw.acct = qty
    return raw, make_engine(raw, regular=REG, clock=Clock(NOW))


async def unknown_leg(s, eng, raw, seq=1, qty=20, symbol="TESTA"):
    """등록 응답에 번호가 없어(만들어졌을 수는 있음) 결과를 모르는 손절 다리 한 건."""
    plan = await seed_holding(s, eng, symbol=symbol)
    raw.create_no_id = True
    await eng._register_leg(s, plan, seq, qty, eng._values_for(plan, seq, "regular", D(10)), "regular")
    raw.create_no_id = False
    return plan


# ── 질문 3 기본값 · 질문 2 표 1 (기다리는 시간) ─────────────────────────────────

def test_defaults_are_conservative():
    assert ob.settle_sec() == 90                      # 기다리는 시간 설정값 기본
    assert ob.list_searchable() is False              # 목록에서 clientOrderId 로 찾을 수 있음 · 기본 「못 찾음」
    assert ob.list_paging_known() is False            # 목록 쪽 나눔 · 기본 「모름」


async def test_no_verdict_inside_wait_window_even_when_everything_would_say_not_created(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90, searchable=True, paging=True)
    raw, eng = await setup()
    raw.create_timeout = True                          # 어느 목록에도 없다
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D(10)), "regular")
        eng.clock.advance(seconds=30)
        out = await ob.reconcile(s, eng, plan)
        assert out["waiting"] == 1 and out["not_created"] == 0
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id))).one()
        assert leg.status == "UNCERTAIN" and plan.state == state.HOLDING          # 그 시간 안에는 없음으로 단정하지 않는다
        eng.clock.advance(seconds=61)
        out = await ob.reconcile(s, eng, plan)
        assert out["not_created"] == 1                                              # 시간이 지난 뒤에야 판정
        assert (await s.get(PlanLeg, leg.id)).status == "CANCELED" and plan.state == state.HOLDING


# ── 질문 2 표 2 (모름 매도 묶음 · 되풀이 알림 · 사람 확정 · resume 이 풀지 않음) ──────────

async def test_unknown_sl_binds_only_its_qty_repeats_alert_and_resume_needs_human(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)                          # 기본 설정: 목록에서 못 찾음 → 사람 확인
    raw, eng = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        eng.clock.advance(seconds=1)
        creates = raw.count("cond_create")
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED
        ln = (await lines(s, plan, state="needs_human"))[0]
        assert ln.qty == 20 and "찾을 수 없는 설정" in json.loads(ln.note)["reason"]
        exp = await ob.exposure(s, plan.id)
        assert exp == {"bound_new": 20, "unknown_modify": 0}                        # 그 수량만 묶음
        # 나머지 모자람(다른 20주)은 계속 다시 건다 · 묶은 20주는 다시 걸지 않는다
        assert sum(l.qty for l in await legs_of(s, plan)) == 40                     # 정지 중에도 묶은 20주는 빼고 나머지 40주만 건다
        assert await eng.ensure_ladder(s, plan) in ("ok", "skipped")                # 더 걸지 않는다
        assert 1 not in [l.seq for l in await legs_of(s, plan)]                     # 결과 모르는 번호는 비워 둔다
        # ⑨ 긴급 알림은 되풀이한다 (600초 안에는 한 번)
        title = "결과 모르는 주문 확인 필요"
        n0 = len([a for a in eng._alerts if a[1] == title])
        await eng.tick_plan(s, plan)
        assert len([a for a in eng._alerts if a[1] == title]) == n0
        eng.clock.advance(seconds=601)
        await eng.tick_plan(s, plan)
        assert len([a for a in eng._alerts if a[1] == title]) == n0 + 1
        # 확인 없이 정지를 풀 수 없다 (묶음을 0 으로 되돌리지 않는다)
        with pytest.raises(state.TransitionError):
            await eng.resume_plan(s, plan)
        assert (await ob.exposure(s, plan.id))["bound_new"] == 20
        # 사람이 「안 만들어짐」 을 확정하면 풀린다
        await ob.human_resolve(s, plan, ln.id, "not_created")
        assert await ob.unresolved_lines(s, plan.id) == []
        raw.acct = 60
        assert await eng.resume_plan(s, plan) == state.HOLDING
        assert sum(l.qty for l in await legs_of(s, plan)) == 60


async def test_human_filled_writes_only_the_confirmed_qty_and_open_links_the_id(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        with pytest.raises(ob.ResolveError):
            await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=25)          # 주문 수량 초과
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=12, remainder_cancelled=True)
        fills = list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL")))
        assert [f.qty for f in fills] == [12] and fills[0].order_ref == f"human{ln.id}"   # 사람이 정한 수량만
        assert ln.state == "closed" and ln.filled_qty == 12
        with pytest.raises(ob.ResolveError):
            await ob.human_resolve(s, plan, ln.id, "not_created")                      # 이미 확인됨
    raw2, eng2 = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng2, raw2, seq=2, symbol="TESTB")
        eng2.clock.advance(seconds=1)
        await ob.reconcile(s, eng2, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        existing = next(iter(raw2.conds))
        with pytest.raises(ob.ResolveError):
            await ob.human_resolve(s, plan, ln.id, "open")                              # 번호 필요
        await ob.human_resolve(s, plan, ln.id, "open", toss_id=existing)
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id))).one()
        assert leg.toss_id == existing and leg.status == "WATCHING"


# ── 질문 2 표 3 (수정: 옛 살아 있음 + 새 모름 공존) ─────────────────────────────────

class ModifyThenFail(FakeRaw):
    once = True

    async def cond_modify(self, s, cond_id, **kw):
        out = await super().cond_modify(s, cond_id, **kw)
        if self.once:
            self.once = False
            raise ExecutionError("시간 초과")
        return out


async def test_modify_unknown_keeps_old_open_and_new_unknown_together(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        old_toss = leg.toss_id
        assert await eng._modify_leg(s, plan, leg, qty=10) is False
        old = (await lines(s, plan, state="open", leg_id=leg.id))[0]
        new = (await lines(s, plan, state="sent_unknown"))[0]
        assert new.replaces_id == old.id and new.qty == 10 and old.state == "open"   # 공존
        assert leg.toss_id == old_toss and leg.status == "WATCHING" and leg.qty == 20
        confirmed = sum(l.qty for l in await legs_of(s, plan))
        assert confirmed == 60                                                         # 보호 수량에는 확인된 것만
        exp = await ob.exposure(s, plan.id)
        assert exp["unknown_modify"] == 10
        assert sizing.exposure_over(confirmed, exp["unknown_modify"], 60) is True      # 넘침 검사에는 둘 다
        assert sizing.exposure_over(confirmed, 0, 60) is False
        before = raw.count("cond_modify")
        assert await eng._modify_leg(s, plan, leg, qty=10) is False                    # 판정될 때까지 새로 보내지 않는다
        assert raw.count("cond_modify") == before
        assert await eng.ensure_ladder(s, plan) == "ok"                                # 모자람이 없으면 그대로 (줄이기도 막지 않는다)


async def test_modify_unknown_links_by_client_id_when_list_searchable(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True)
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        old = leg.toss_id
        await eng._modify_leg(s, plan, leg, qty=10)
        eng.clock.advance(seconds=1)
        creates = raw.count("cond_create")
        out = await ob.reconcile(s, eng, plan)
        assert out["linked"] == 1 and leg.toss_id != old and leg.qty == 10
        assert [l.state for l in await lines(s, plan, leg_id=leg.id) if l.replaces_id is None][0] in ("closed", "open")
        assert raw.count("cond_create") == creates and await ob.unresolved_lines(s, plan.id) == []


# ── 질문 2 표 4 (부모 조건주문 – 자식 주문 관계) ────────────────────────────────────

async def test_parent_child_relation_is_in_the_ledger(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        parent = (await lines(s, plan, leg_id=leg.id, kind="cond"))[0]
        raw.trigger(leg.toss_id, fill=False)
        raw.limits["T" + leg.toss_id] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=20, price=D("9.5"), filled=0,
                                             remaining=20, avg=None, client_id="c")
        await eng.sync_orders(s, plan)
        child = (await lines(s, plan, toss_id="T" + leg.toss_id))[0]
        assert child.parent_id == parent.id and child.kind == "limit" and child.state == "open"   # 부모 줄 아래 자식 주문
        raw.limits["T" + leg.toss_id]["status"] = "CANCELED"
        await eng.sync_orders(s, plan)
        assert (await s.get(PlanOrderBook, child.id)).state == "closed"
        assert await sizing.accepted_sell(s, plan.id) == 0


# ── 질문 2 표 6 · 7 · 질문 3 (쪽 나눔 · 가짜 브로커 네 경우) ────────────────────────────

async def test_paging_unknown_never_treats_absence_as_not_created(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True, paging=False)
    raw, eng = await setup()
    raw.create_timeout = True                              # 정말 만들어지지 않았지만 우리는 그것을 증명할 수 없다
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D(10)), "regular")
        eng.clock.advance(seconds=1)
        out = await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan))[0]
        assert out["needs_human"] == 1 and ln.state == "needs_human" and "쪽 나눔" in json.loads(ln.note)["reason"]
        assert plan.state == state.HALTED


async def test_fake_broker_case_list_without_client_order_id(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True)
    raw, eng = await setup()
    raw.list_hide_client_id = True                         # 목록 응답에 clientOrderId 가 없다
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan))[0]
        assert ln.state == "needs_human" and ln.toss_id is None                        # 연결하지 않고 사람에게


async def test_fake_broker_case_order_appears_late(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90, searchable=True)
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        raw.create_no_id = True
        await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D(10)), "regular")
        raw.create_no_id = False
        cid = next(iter(raw.conds))
        raw.list_hidden_ids = {cid}                                                    # 목록 반영 지연
        eng.clock.advance(seconds=30)
        out = await ob.reconcile(s, eng, plan)
        assert out["waiting"] == 1 and (await lines(s, plan))[0].state == "sent_unknown"   # 기다리는 시간 안 · 단정 없음
        raw.list_hidden_ids = set()                                                    # 늦게 나타남
        eng.clock.advance(seconds=65)
        out = await ob.reconcile(s, eng, plan)
        assert out["linked"] == 1
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id))).one()
        assert leg.toss_id == cid and leg.status == "WATCHING" and plan.state == state.HOLDING


async def test_fake_broker_case_list_truncated(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True)
    raw, eng = await setup()
    raw.conds["OTHER"] = dict(id="OTHER", status="WATCHING", symbol="TESTA", side="SELL", qty=5, watch=D("1"), order=D("1"),
                              client_id="x", order_id=None, filled=0, remaining=5, avg=None)
    raw.list_limit = 1                                     # 앞 1줄에서 잘림 · 우리 주문은 뒤에 있다
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan))[0]
        assert ln.state == "needs_human"                                               # 잘린 목록의 부재를 안 만들어짐 근거로 쓰지 않는다


async def test_fake_broker_case_same_key_twice(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0, searchable=True)
    raw, eng = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        first = next(iter(raw.conds.values()))
        raw.conds["DUP"] = {**first, "id": "DUP"}                                       # 같은 clientOrderId 둘
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan))[0]
        assert ln.state == "needs_human" and "둘 이상" in json.loads(ln.note)["reason"] and ln.toss_id is None


# ── 질문 4 (계좌 보유는 상한 · 경보에만 · 체결 근거 아님) ─────────────────────────────

async def _entry(s, eng, raw, qty=6, buy=9.7):
    plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": buy, "buy_order": buy, "qty": qty})
    plan.state = state.APPROVED
    await eng.start_entry(s, plan)
    return plan


async def test_unknown_buy_never_writes_fill_from_account_change_alerts_and_human_confirms(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan = await _entry(s, eng, raw)
        raw.limit_uncertain = False
        raw.acct = 3                                                                    # 계좌 보유가 늘었다
        eng.clock.advance(seconds=1)
        await eng.tick_plan(s, plan)
        assert await sizing.plan_qty(s, plan) == 0                                      # 체결 줄을 만들지 않는다
        assert not list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id)))
        assert any(a[1] == "매수 체결 가능성" and a[0] == "critical" for a in eng._alerts)   # ⑨ 긴급 경보
        n = len([a for a in eng._alerts if a[1] == "매수 체결 가능성"])
        await eng.tick_plan(s, plan)
        assert len([a for a in eng._alerts if a[1] == "매수 체결 가능성"]) == n          # 되풀이는 600초 간격
        ln = (await lines(s, plan, state="needs_human"))[0]
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=3, remainder_cancelled=True)      # 사람이 체결 수량을 확정
        assert await sizing.plan_qty(s, plan) == 3
        await eng.tick_plan(s, plan)                                                    # 그러면 손절이 걸린다
        assert sum(l.qty for l in await legs_of(s, plan)) == 3


async def test_unknown_sell_keeps_reservation_and_never_records_sale_from_holdings(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup(price="9.60")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        raw.limit_uncertain = True
        leg = (await legs_of(s, plan))[0]
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=leg)
        raw.limit_uncertain = False
        raw.limits.clear()
        raw.acct = 40                                                                   # 보유가 줄었지만 체결 근거가 아니다
        eng.clock.advance(seconds=1)
        await eng.tick_plan(s, plan)
        assert not list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL")))
        assert await sizing.accepted_sell(s, plan.id) == 40                             # 모르는 예약 둘 다 유지 (조회가 비어도 풀지 않음)
        for ln in await lines(s, plan, state="needs_human"):
            await ob.human_resolve(s, plan, ln.id, "not_created")
        assert await sizing.accepted_sell(s, plan.id) == 0
        raw.acct = 60
        assert await eng.ensure_ladder(s, plan) in ("fixed", "ok")


# ── 권고 5 · 8 · 2순위 값 연결 제거 ─────────────────────────────────────────────

async def test_each_send_gets_its_own_ledger_line_and_new_key(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.fail_modify = 1
        assert await eng._modify_leg(s, plan, leg, qty=10) is False
        first = (await lines(s, plan, state="sent_unknown"))[0]
        assert await eng._modify_leg(s, plan, leg, qty=10) is False
        assert raw.count("cond_modify") == 1                                            # 모름이 풀릴 때까지 다시 보내지 않는다
        await ob.human_resolve(s, plan, first.id, "not_created")
        assert await eng._modify_leg(s, plan, leg, qty=10) is True
        keys = [c[5] for c in raw.calls if c[0] == "cond_modify"]
        assert len(keys) == 2 and keys[0] != keys[1]                                    # 보낼 때마다 새 키
        assert len(await lines(s, plan, leg_id=leg.id)) >= 3                            # 보낼 때마다 한 줄


async def test_empty_single_lookup_goes_through_the_reconcile_not_instant_cancel(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.get_blind = {leg.toss_id}                                                   # 단건 조회가 빈 값
        raw.list_hidden_ids = {leg.toss_id}                                             # 목록에도 없다
        await eng.sync_orders(s, plan)
        assert leg.status == "UNCERTAIN" and plan.state == state.HALTED                 # 바로 CANCELED 가 아니다
        assert any(l.state == "needs_human" for l in await lines(s, plan))
    raw2, eng2 = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng2, symbol="TESTB")
        await eng2.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw2.conds[leg.toss_id]["status"] = "CANCELED"
        raw2.get_blind = {leg.toss_id}                                                  # 조회는 비었지만 닫힌 목록에서 확인된다
        await eng2.sync_orders(s, plan)
        assert leg.status == "CANCELED" and plan.state == state.HOLDING


async def test_value_match_candidates_are_shown_not_auto_linked_and_many_candidates_still_resolvable(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        old = leg.toss_id
        raw.conds["APPX"] = dict(id="APPX", status="WATCHING", symbol="TESTA", side="SELL", qty=10, watch=D("9"), order=D("8.9"),
                                 client_id="app", order_id=None, filled=0, remaining=10, avg=None)   # 앱에서 같은 수량으로 건 주문
        await eng._modify_leg(s, plan, leg, qty=10)
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        cands = {c["toss_id"] for c in json.loads(ln.note)["candidates"]}
        assert "APPX" in cands and len(cands) >= 2                                      # 후보가 여럿
        assert leg.toss_id == old                                                       # 값이 같다고 자동으로 잇지 않는다
        await ob.human_resolve(s, plan, ln.id, "not_created")                           # 후보가 여럿이어도 기록이 풀린다
        assert await ob.unresolved_lines(s, plan.id) == []


async def test_resync_reports_unknown_orders_as_not_ok(plan_db, monkeypatch):
    from backend.execution.plan import resync

    cfg(monkeypatch, settle=0)
    raw, eng = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw)
        eng.clock.advance(seconds=1)
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["unknown_orders"] == 1 and rep["ok"] is False


# ── API: 결과 모르는 주문 확인 · 승인 뒤 발표 시각 ───────────────────────────────

async def _api_line(plan_id, role="buy", side="BUY", qty=6, state_="needs_human"):
    async with get_session() as s:
        s.add(PlanOrderBook(plan_id=plan_id, client_order_id="c1", kind="limit", role=role, side=side, qty=qty, price=9.5,
                            state=state_, sent_at=NOW, note=json.dumps({"reason": "시험", "candidates": []})))


async def test_unknown_orders_api_list_and_resolve_rules(api):
    plan = await mk_plan(api)                                                           # 모의 계획 (코드 없음)
    await _api_line(plan["id"])
    cookie(api)
    r = await api.get(f"/api/v1/plans/{plan['id']}/unknown-orders")
    j = r.json()
    assert r.status_code == 200 and len(j["orders"]) == 1 and j["orders"][0]["reason"] == "시험"
    assert j["settle_sec"] == 90 and j["list_searchable"] is False and j["list_paging_known"] is False
    lid = j["orders"][0]["id"]
    url = f"/api/v1/plans/{plan['id']}/unknown-orders/{lid}/resolve"
    api.cookies.clear()
    assert (await api.post(url, json={"decision": "not_created"}, headers=hdr())).status_code == 403   # 헤더는 거부
    cookie(api)
    assert (await api.post(url, json={"decision": "not_created"}, headers={"Origin": "https://evil.example.com"})).status_code == 403
    assert (await api.post(url, json={"decision": "maybe"}, headers=OK_ORIGIN)).status_code == 422
    r = await api.post(url, json={"decision": "filled", "filled_qty": 9}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "resolve"          # 주문 수량 초과
    r = await api.post(url, json={"decision": "filled", "filled_qty": 4, "remainder_cancelled": True}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["remaining"] == 0 and r.json()["order"]["state"] == "closed"
    async with get_session() as s:
        assert [f.qty for f in await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan["id"]))] == [4]
    d = (await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())).json()
    assert d["unknown_orders"] == 0


async def test_unknown_orders_resolve_needs_telegram_code_for_live_plan(api):
    plan = await mk_plan(api, "live")
    await _api_line(plan["id"], qty=6)
    cookie(api)
    lid = (await api.get(f"/api/v1/plans/{plan['id']}/unknown-orders")).json()["orders"][0]["id"]
    url = f"/api/v1/plans/{plan['id']}/unknown-orders/{lid}/resolve"
    r = await api.post(url, json={"decision": "not_created"}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "code_required"     # 실전 · 시험은 확인 코드
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "resolve_order", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    r = await api.post(url, json={"decision": "not_created", "challenge_id": c.json()["challenge_id"], "code": api.phone.code},
                       headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["order"]["state"] == "not_created"


async def test_announce_after_approval_is_cookie_only_but_draft_edit_keeps_header(api):
    plan = await mk_plan(api)
    api.cookies.clear()
    ok = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"announce_at": "2026-12-10T22:00:00+09:00"}}, headers=hdr())
    assert ok.status_code == 200                                                         # 초안 수정은 쿠키 · 헤더 모두
    async with get_session() as s:
        (await s.get(Plan, plan["id"])).state = state.HOLDING
    no = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"announce_at": "2026-12-11T22:00:00+09:00"}}, headers=hdr())
    assert no.status_code == 403                                                         # 승인 뒤 발표 시각은 쿠키 전용
    cookie(api)
    assert (await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"announce_at": "2026-12-11T22:00:00+09:00"}})).status_code == 403   # Origin 필요
    ok = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"announce_at": "2026-12-11T22:00:00+09:00"}}, headers=OK_ORIGIN)
    assert ok.status_code == 200                                                         # 쿠키 + Origin · 텔레그램 코드 없음
