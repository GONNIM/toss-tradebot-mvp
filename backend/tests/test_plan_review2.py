"""1116-01 · 재검토 지적 반영 시험 (가짜 토스 · 가상 종목 · 실제 호출 0)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.execution.exceptions import ExecutionError
from backend.execution.plan import sizing, state
from backend.execution.plan.engine import runtime_of, set_runtime
from backend.execution.plan.models import Plan, PlanFill, PlanLeg, PlanLegPending, PlanSellReservation
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401

D = Decimal
NOW = datetime(2026, 11, 20, 15, 0)
REG = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))


async def legs_of(s, plan, role="sl", status="WATCHING"):
    return list(await s.scalars(select(PlanLeg).where(
        PlanLeg.plan_id == plan.id, PlanLeg.role == role, PlanLeg.status == status).order_by(PlanLeg.seq)))


async def setup(price="10", qty=60, **kw):
    raw = FakeRaw(price)
    raw.acct = qty
    return raw, make_engine(raw, regular=kw.pop("regular", REG), clock=Clock(NOW), **kw)


async def entry_plan(s, eng, raw, qty=6, buy=9.7):
    """진입 중(ENTRY_ARMED) 계획 · 가격이 매수 감시가 아래라 일반 지정가 매수가 걸린다."""
    plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": buy, "buy_order": buy, "qty": qty})
    plan.state = state.APPROVED
    await eng.start_entry(s, plan)
    leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "buy"))).one()
    return plan, leg


# ── 새 막음 1 · 진입 중 일부 체결 뒤 스위치 끔 · 정지 ───────────────────────────────

async def test_partial_entry_fill_during_cancel_then_switch_off_still_gets_stop_legs(plan_db):
    sw = {"live": True, "paper": True}
    raw, eng = await setup(price="9.60", qty=0)
    eng.switches = lambda: sw
    async with get_session() as s:
        plan, leg = await entry_plan(s, eng, raw)
        assert plan.state == state.ENTRY_ARMED
        raw.limits[leg.toss_id].update(filled=3, remaining=3, avg=D("9.5"))      # 마지막 동기화 뒤에 3주 체결
        raw.acct = 3
        sw["live"] = False
        await eng.cancel_buys_on_switch_off(s, plan)                              # 끌 때 취소하며 마지막 체결을 읽는다
        await eng.tick_plan(s, plan)                                              # 다음 걸음: 보유가 있으니 손절을 건다
        assert plan.state == state.HOLDING
        assert sum(l.qty for l in await legs_of(s, plan)) == 3
        assert await sizing.plan_qty(s, plan) == 3


async def test_partial_entry_fill_then_halt_keeps_halted_but_hangs_stops(plan_db):
    raw, eng = await setup(price="9.60", qty=0)
    async with get_session() as s:
        plan, leg = await entry_plan(s, eng, raw)
        raw.limits[leg.toss_id].update(filled=3, remaining=3, avg=D("9.5"))
        raw.acct = 3
        await eng.stop_plan(s, plan)                                               # 정지 = 대기 매수 취소 + 마지막 체결 읽기
        assert plan.state == state.HALTED and plan.prev_state == state.ENTRY_ARMED
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED and plan.prev_state == state.HOLDING     # 정지 유지 · 정지 직전 상태는 보유
        assert sum(l.qty for l in await legs_of(s, plan)) == 3                      # 정지 중에도 손절 다리


# ── 새 막음 2 · 결과를 모르는 매수 ──────────────────────────────────────────────────

async def test_uncertain_buy_filled_instantly_is_found_in_closed_list_and_protected(plan_db):
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True                                                      # 만들고도 응답 오류
    async with get_session() as s:
        plan, leg = await entry_plan(s, eng, raw)
        assert leg.status == "UNCERTAIN" and raw.count("limit_create") == 1
        oid = next(iter(raw.limits))
        raw.fill_limit(oid)                                                         # 곧바로 전량 체결 → 열린 목록에서 사라짐
        raw.limits[oid]["avg"] = D("9.5")
        raw.acct = 6
        raw.limit_uncertain = False
        await eng.tick_plan(s, plan)
        assert await sizing.plan_qty(s, plan) == 6 and plan.state == state.HOLDING   # 닫힌 목록에서 이어 체결을 읽었다
        assert sum(l.qty for l in await legs_of(s, plan)) == 6
        assert raw.count("limit_create") == 1


async def test_uncertain_buy_in_no_list_uses_account_increase_as_fill(plan_db):
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan, leg = await entry_plan(s, eng, raw)
        raw.limits.clear()                                                          # 어느 목록에도 없다
        raw.acct = 6                                                                # 그런데 계좌 보유가 늘었다
        await eng.tick_plan(s, plan)
        assert await sizing.plan_qty(s, plan) == 6 and plan.state == state.HOLDING
        assert sum(l.qty for l in await legs_of(s, plan)) == 6


async def test_uncertain_buy_not_found_anywhere_halts_and_resume_never_rebuys(plan_db):
    raw, eng = await setup(price="9.60", qty=0)
    raw.limit_uncertain = True
    async with get_session() as s:
        plan, leg = await entry_plan(s, eng, raw)
        raw.limits.clear()                                                          # 목록에도 없고 계좌 보유도 그대로
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED and runtime_of(plan).get("no_rebuy") is True
        raw.limit_uncertain = False
        assert await eng.resume_plan(s, plan) == state.ENTRY_ARMED
        for _ in range(3):
            await eng.tick_plan(s, plan)
        assert raw.count("limit_create") == 1 and raw.count("cond_create") == 0     # 재개해도 자동 재매수 0


# ── 새 막음 3 · 결과를 모르는 즉시 매도 ─────────────────────────────────────────────

async def _uncertain_sell(raw, eng, s):
    plan = await seed_holding(s, eng)
    await eng.ensure_ladder(s, plan)
    raw.limit_uncertain = True
    raw.price = D("9.60")
    leg = (await legs_of(s, plan))[0]
    await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=leg)
    raw.limit_uncertain = False
    raw.limits.clear()
    return plan


async def test_uncertain_sell_not_found_and_holdings_dropped_records_sale_and_releases(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await _uncertain_sell(raw, eng, s)
        raw.acct = 40                                                               # 계좌 보유가 20 줄었다 → 팔렸다
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 0
        sold = sum(f.qty for f in await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL")))
        assert sold == 20 and await sizing.plan_qty(s, plan) == 40


async def test_uncertain_sell_not_found_and_holdings_same_releases_and_rehangs(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await _uncertain_sell(raw, eng, s)
        raw.price = D("10")
        await eng.sync_orders(s, plan)                                              # 계좌 보유 그대로 → 안 팔렸다
        assert await sizing.accepted_sell(s, plan.id) == 0                          # 예약이 영구히 남지 않는다
        assert await eng.ensure_ladder(s, plan) == "fixed"
        assert sum(l.qty for l in await legs_of(s, plan)) == 60                      # 보호 다리를 다시 건다


async def test_resume_cleans_reservations_without_order_ref(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        r = await sizing.reserve(s, plan.id, "immediate", 20, None)                 # 주문 번호 없이 남은 예약
        await state.halt(s, plan, "시험")
        await eng.resume_plan(s, plan) if False else None
        raw.acct = 60
        eng.kill_state = lambda: (False, True)
        try:
            await eng.resume_plan(s, plan)
        except state.TransitionError:
            pass                                                                    # 불변식 때문에 거부돼도 정리는 먼저 일어난다
        assert r.active is False


# ── 새 높음 1 · 수정 불확실 뒤 중복 손절 ────────────────────────────────────────────

class ModifyThenFail(FakeRaw):
    once = True

    async def cond_modify(self, s, cond_id, **kw):
        await super().cond_modify(s, cond_id, **kw)
        if self.once:
            self.once = False
            raise ExecutionError("시간 초과")                                        # 수정은 됐는데 응답이 오류


async def test_uncertain_modify_links_new_order_next_tick_without_duplicate_legs(plan_db):
    raw = ModifyThenFail("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        old = leg.toss_id
        assert await eng._modify_leg(s, plan, leg, qty=10) is False
        assert (await s.scalars(select(PlanLegPending))).first() is not None        # 수정 중 기록이 남음
        creates = raw.count("cond_create")
        assert await eng.ensure_ladder(s, plan) == "skipped"                        # 기록이 있으면 새 다리를 걸지 않는다
        await eng.tick_plan(s, plan)                                                # 매 걸음 맨 앞에서 풀어 새 번호를 잇는다
        assert (await s.scalars(select(PlanLegPending))).first() is None
        assert leg.toss_id != old and leg.status == "WATCHING" and leg.qty == 10
        assert raw.count("cond_create") == creates                                  # 중복 등록 0


# ── 새 높음 2 · TP1 불확실 ─────────────────────────────────────────────────────────

async def test_tp1_uncertain_is_recorded_first_and_linked_not_reissued(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        n = raw.count("cond_create")
        raw.create_no_id = True
        await eng._tp1_step(s, plan, True)
        await eng._tp1_step(s, plan, True)
        await eng._tp1_step(s, plan, True)
        assert raw.count("cond_create") == n + 1                                    # 한 번만 냄
        tp = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "tp1"))).one()
        assert tp.status == "UNCERTAIN"
        raw.create_no_id = False
        await eng.sync_orders(s, plan)
        assert tp.status == "WATCHING" and tp.toss_id in raw.conds                  # clientOrderId 로 찾아 이음


# ── 새 높음 3 · 호출 전에 확인 대기 commit ─────────────────────────────────────────

class ProbeRaw(FakeRaw):
    snaps: list

    async def limit_create(self, s, **kw):
        rows = list(await s.scalars(select(PlanSellReservation)))
        self.snaps.append([(r.uncertain, r.client_order_id, r.order_ref) for r in rows if r.active])
        return await super().limit_create(s, **kw)


async def test_reservation_is_uncertain_before_toss_call_and_cleared_after(plan_db):
    raw = ProbeRaw("9.60")
    raw.snaps = []
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        before = raw.snaps[0][0]
        assert before[0] is True and before[1] and before[2] is None                # 호출 직전: 확인 대기 · 고정 키 · 번호 없음
        r = (await s.scalars(select(PlanSellReservation))).one()
        assert r.uncertain is False and r.order_ref in raw.limits                    # 성공 뒤: 해제 · 번호 저장


async def test_tp1_watch_and_reprice_also_mark_uncertain_before_call(plan_db):
    raw = ProbeRaw("12.00")
    raw.snaps = []
    raw.acct = 70                                                                   # 계획 밖 보유 → TP1 감시 모드
    clock = Clock(NOW)
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"tp1_watch": 12.0, "tp1_order": 12.0})
        await eng.ensure_ladder(s, plan)
        await eng._tp1_step(s, plan, True)
        assert raw.snaps and raw.snaps[0][-1][0] is True                            # TP1 감시 매도도 호출 전 확인 대기
        r = (await s.scalars(select(PlanSellReservation).where(PlanSellReservation.kind == "tp1_watch"))).one()
        assert r.uncertain is False and r.order_ref
        # 시간 손절 다시 내기
        raw.price = D("10")
        r2 = await sizing.reserve(s, plan.id, "time_stop", 10, None)
        raw.limits["LX"] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=10, price=D("10.3"), filled=0, remaining=10,
                                avg=None, client_id="x")
        r2.order_ref, r2.order_price, r2.leg_seq = "LX", 10.3, 1
        raw.snaps.clear()
        await eng._cancel_and_reprice(s, plan, r2, D("10"))
        assert raw.snaps and raw.snaps[0][-1][0] is True


# ── 새 높음 4 · UNKNOWN 은 닫힘이 아니다 ───────────────────────────────────────────

async def test_unknown_order_status_keeps_reservation_and_alerts_once(plan_db):
    raw, eng = await setup(price="9.60")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        oid = next(iter(raw.limits))
        raw.limits[oid]["status"] = "UNKNOWN"
        for _ in range(3):
            await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20                          # 예약 유지
        assert len([a for a in eng._alerts if a[1] == "접수된 매도 상태 모름"]) == 1     # 알림 1번


async def test_unknown_child_of_triggered_leg_keeps_reservation(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.trigger(leg.toss_id, fill=False)
        raw.limits["T" + leg.toss_id] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=20, price=D("9.5"), filled=0,
                                             remaining=20, avg=None, client_id="c")
        await eng.sync_orders(s, plan)
        raw.limits["T" + leg.toss_id]["status"] = "UNKNOWN"
        raw.conds[leg.toss_id]["status"] = "UNKNOWN"
        for _ in range(2):
            await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20
        assert len([a for a in eng._alerts if a[1] == "발동된 주문 상태 모름"]) == 1


# ── 새 높음 5 · 못 찾은 다리 수량만 막고 나머지 보호는 계속 ──────────────────────────

async def test_lost_leg_blocks_only_its_qty_other_shortage_still_rehung(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        legs = await legs_of(s, plan)
        legs[2].status = "CANCELED"                                                  # 3번 다리를 지우고 다시 걸다가
        raw.create_timeout = True                                                    # 시간 초과 · 만들어지지 않음 · 목록에도 없음
        await eng.ensure_ladder(s, plan)
        await eng.tick_plan(s, plan)                                                 # 못 찾음 → 20주만 막고 HALTED
        assert plan.state == state.HALTED and runtime_of(plan)["lost_sl_qty"] == 20
        raw.create_timeout = False
        legs[0].status = "EXPIRED"                                                   # 다른 다리가 만료돼 20주가 더 모자람
        await eng.ensure_ladder(s, plan)                                             # 정지 중에도 막히지 않은 20주는 다시 건다
        assert sum(l.qty for l in await legs_of(s, plan)) == 40
        assert runtime_of(plan)["lost_sl_qty"] == 20                                 # 막은 20주는 사람이 확인할 때까지


# ── 중간 1 · 정지 · 수정은 충돌해도 서버 안에서 재시도 ───────────────────────────────

async def test_stop_and_edit_retry_on_stale_conflict(plan_db, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.orm.exc import StaleDataError

    from backend.api.main import app
    from backend.tests.test_plan_api import OK_ORIGIN, PARAMS, TOKEN  # noqa: F401

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("sniper_session", TOKEN)
        r = await ac.post("/api/v1/plans", json={"symbol": "TESTA", "mode": "paper", "params": PARAMS}, headers=OK_ORIGIN)
        pid = r.json()["plan"]["id"]
        async with get_session() as s:
            p = await s.get(Plan, pid)
            p.state = state.HOLDING
        real_halt, calls = state.halt, {"n": 0}

        async def flaky(s, plan, reason):
            calls["n"] += 1
            if calls["n"] == 1:
                raise StaleDataError("충돌")
            return await real_halt(s, plan, reason)

        monkeypatch.setattr(state, "halt", flaky)
        r = await ac.post(f"/api/v1/plans/{pid}/stop", headers=OK_ORIGIN)
        assert r.status_code == 200 and r.json()["halted"] is True and calls["n"] == 2   # 첫 충돌은 서버 안에서 다시 읽고 성공
        monkeypatch.setattr(state, "halt", real_halt)
        from backend.execution.plan import engine as engmod

        real_upd, n2 = engmod.PlanEngine.update_draft, {"n": 0}

        async def flaky_upd(self, s, plan, values, **kw):
            n2["n"] += 1
            if n2["n"] == 1:
                raise StaleDataError("충돌")
            return await real_upd(self, s, plan, values, **kw)

        monkeypatch.setattr(engmod.PlanEngine, "update_draft", flaky_upd)
        r = await ac.patch(f"/api/v1/plans/{pid}", json={"values": {"announce_at": "2026-12-10T22:00:00+09:00"}}, headers=OK_ORIGIN)
        assert r.status_code == 200 and n2["n"] == 2


# ── 중간 2 · 표 만들기 재시도 ─────────────────────────────────────────────────────────

async def test_start_executor_retries_table_creation(monkeypatch):
    from backend.execution.plan import runner
    import backend.services.db as dbmod

    calls = {"n": 0}

    async def flaky_init():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("동시에 만들다 겹침")

    async def fast_sleep(x):
        return None

    monkeypatch.setattr(runner, "executor_enabled", lambda: True)
    monkeypatch.setattr(dbmod, "init_db", flaky_init)
    monkeypatch.setattr(runner.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(runner, "acquire_lock", lambda *a, **k: None)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(runner, "default_notify", noop)
    assert await runner.start_executor(asyncio.Event()) is None and calls["n"] == 3   # 3번째에 성공해 잠금 단계까지 감
    calls["n"] = -10                                                                    # 계속 실패하면 알리고 시작하지 않는다
    sent = []

    async def cap(level, title, body, category):
        sent.append(title)

    monkeypatch.setattr(runner, "default_notify", cap)
    assert await runner.start_executor(asyncio.Event()) is None and sent == ["계획 실행기 시작 안 함"]


# ── 중간 3 · 인수 대기 중 정지 알림 ───────────────────────────────────────────────────

async def test_halted_adopt_pending_alerts_with_remaining_app_orders(plan_db):
    raw = FakeRaw("10")
    raw.acct = 30
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    raw.conds["APP1"] = dict(id="APP1", status="WATCHING", symbol="TESTA", side="SELL", qty=30, watch=D("9"), order=D("8.9"),
                             client_id="app", order_id=None, filled=0, remaining=30, avg=None)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", source="adopt", params={"adopt": {"qty": 30, "avg_price": 10.0}})
        plan.state, plan.approved_at = state.APPROVED, NOW
        await eng.adopt_approve(s, plan)
        await state.halt(s, plan, "계획 정지")
        await eng.tick_plan(s, plan)
        assert plan.state == state.CANCELLED
        a = [x for x in eng._alerts if x[1] == "인수 취소 · 보호 없음"]
        assert a and a[0][0] == "critical" and "1건" in a[0][2]


# ── 중간 4 · 진입 매수를 걸음마다 다시 내지 않는다 ───────────────────────────────────

async def test_entry_armed_does_not_reissue_buy_every_tick_and_sanity_alert_once(plan_db):
    raw, eng = await setup(price="20")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 5.0, "buy_order": 5.0, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)                                               # 직전가 ±40% 밖 → 매수 등록 거부
        for _ in range(5):
            await eng.tick_plan(s, plan)
        assert raw.count("cond_create") == 0 and raw.count("limit_create") == 0
        assert len([a for a in eng._alerts if a[1] == "등록 거부 · 값 점검"]) == 1       # 알림 1번


# ── 낮음 · Kill 매도도 멈춤 때 접수된 지정가도 취소 · 걸음 캐시가 새지 않게 ──────────────

async def test_kill_sell_stop_also_cancels_accepted_limit_sells(plan_db):
    kill = {"v": (False, True)}
    raw = FakeRaw("9.60")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    eng.kill_state = lambda: kill["v"]
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="time_stop", old_leg=None)
        oid = next(iter(raw.limits))
        raw.limits[oid].update(filled=4, remaining=16, avg=D("9.4"))
        kill["v"] = (True, False)
        await eng.tick_plan(s, plan)
        assert ("limit_cancel", oid) in raw.calls and raw.limits[oid]["status"] == "CANCELED"
        assert await sizing.accepted_sell(s, plan.id) == 0
        assert sum(f.qty for f in await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL"))) == 4


async def test_resync_does_not_use_tick_cache(plan_db):
    from backend.execution.plan import resync

    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        eng.gate.begin_tick()
        assert eng.gate._tick_active is True
        await resync.resync_plan(s, eng, plan)
        assert eng.gate._tick_active is False and eng.gate._acct_cache == {}
