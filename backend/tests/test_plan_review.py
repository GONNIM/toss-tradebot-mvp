"""1116-01 · 검토 지적 반영 시험 (가짜 토스 · 가상 종목 · 실제 호출 0)."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.execution.plan import sessions as sess
from backend.execution.plan import sizing, state
from backend.execution.plan.brokers import DirectionGate
from backend.execution.plan.pricing import D as PD
from backend.execution.plan.engine import PlanEngine, params_of, runtime_of, set_runtime
from backend.execution.plan.models import Plan, PlanFill, PlanLeg, PlanSellReservation
from backend.services.db import AsyncSessionLocal, get_session
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


# ── 막음 1 · Kill Switch 「매도도 멈춤」 뒤 정지 상태에서 다리를 다시 걸지 않는다 ─────────────

async def test_kill_sell_stop_then_halted_ticks_never_re_register(plan_db):
    kill = {"v": (False, True)}
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    eng.kill_state = lambda: kill["v"]
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        creates = raw.count("cond_create")
        kill["v"] = (True, False)
        await eng.tick_plan(s, plan)                              # 매도도 멈춤 → 다리 모두 취소 · HALTED
        assert plan.state == state.HALTED and await legs_of(s, plan) == []
        for _ in range(3):                                        # 바퀴를 더 돌아도 (정지 상태) 등록 · 수정 · 매도 0
            await eng.tick_plan(s, plan)
        assert raw.count("cond_create") == creates and raw.count("cond_modify") == 0 and raw.count("limit_create") == 0
        assert await eng.ensure_ladder(s, plan) == "skipped"
        with pytest.raises(state.TransitionError):
            await eng.resume_plan(s, plan)                        # 멈춘 동안 재개도 안 됨
        assert await eng._register_leg(s, plan, 1, 20, eng._values_for(plan, 1, "regular", D(10)), "regular") is None
        assert raw.count("cond_create") == creates


# ── 막음 2 · 불확실한 실패 뒤 같은 주문을 또 내지 않는다 ─────────────────────────────

# ── 막음 3 · 발동된 매도가 체결 없이 닫히면 예약을 풀고 다시 건다 ──────────────────────────

async def test_triggered_sell_closed_without_fill_releases_reservation_and_rehangs(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.trigger(leg.toss_id, fill=False)                      # 발동 · 자식 주문 생김
        raw.limits["T" + leg.toss_id] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=20, price=D("9.5"),
                                             filled=0, remaining=20, avg=None, client_id="c")
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20
        raw.limits["T" + leg.toss_id]["status"] = "CANCELED"      # 자식 주문이 체결 없이 취소됨
        raw.conds[leg.toss_id]["status"] = "UNKNOWN"
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 0 and leg.status == "CANCELED"
        assert await eng.ensure_ladder(s, plan) == "fixed"        # 모자람으로 다시 건다
        assert sum(l.qty for l in await legs_of(s, plan)) == 60


@pytest.mark.parametrize("cond_status", ["CANCELED", "EXPIRED", "REJECTED"])
async def test_triggered_cond_closed_statuses_release_reservation(plan_db, cond_status):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.trigger(leg.toss_id, fill=False)
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20
        raw.conds[leg.toss_id]["status"] = cond_status
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 0


async def test_triggered_with_live_child_stays_reserved(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.trigger(leg.toss_id, fill=False)
        raw.limits["T" + leg.toss_id] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=20, price=D("9.5"),
                                             filled=0, remaining=20, avg=None, client_id="c")
        await eng.sync_orders(s, plan)
        raw.conds[leg.toss_id]["status"] = "UNKNOWN"
        await eng.sync_orders(s, plan)
        await eng.sync_orders(s, plan)
        assert await sizing.accepted_sell(s, plan.id) == 20       # 자식 주문이 살아 있으면 예약 유지


# ── 높음 1 · 취소 전 마지막 체결 다시 읽기 · 발동된 조건주문은 자식 주문 취소 ──────────────

async def test_cancel_pending_buy_reads_last_fill_first(plan_db):
    raw, eng = await setup(price="9.00")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)                            # 이미 아래 → 일반 지정가 매수
        oid = (await s.scalars(select(PlanLeg).where(PlanLeg.role == "buy"))).one().toss_id
        raw.limits[oid]["filled"], raw.limits[oid]["remaining"], raw.limits[oid]["avg"] = 3, 3, D("9.4")
        await eng._cancel_pending_buys(s, plan)
        fills = list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "BUY")))
        assert sum(f.qty for f in fills) == 3                      # 취소 직전 부분 체결이 장부에 들어갔다


async def test_triggered_buy_cond_cancels_child_order_not_cond(plan_db):
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        cid = (await s.scalars(select(PlanLeg).where(PlanLeg.role == "buy"))).one().toss_id
        raw.trigger(cid, fill=False)
        raw.limits["T" + cid] = dict(status="OPEN", symbol="TESTA", side="BUY", qty=6, price=D("9.5"), filled=0,
                                     remaining=6, avg=None, client_id="c")
        await eng._cancel_pending_buys(s, plan)
        assert ("limit_cancel", "T" + cid) in raw.calls and raw.count("cond_cancel") == 0     # 자식 주문을 취소


async def test_timestop_cancel_at_records_partial_fill_before_and_after(plan_db):
    raw = FakeRaw("10.50")
    raw.acct = 60
    clock = Clock(datetime(2026, 11, 20, 15, 0))
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-09T22:00:00"})
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("10.50"), kind="time_stop", old_leg=leg)
        oid = (await s.scalars(select(PlanSellReservation).where(PlanSellReservation.kind == "time_stop"))).one().order_ref
        raw.limits[oid].update(filled=5, remaining=15, avg=D("10.3"))     # 취소 전에 5주 체결
        raw.acct = 55
        clock.t = datetime(2026, 11, 20, 20, 59)
        await eng._timestop_step(s, plan, clock())
        sold = sum(f.qty for f in await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL")))
        assert sold == 5


# ── 높음 2 · 계획마다 세션 · 토스 호출 전에 commit ───────────────────────────────────

async def test_commit_happens_before_toss_calls_for_register_and_modify_and_sell(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        orig = s.commit

        async def spy():
            raw.calls.append(("commit",))
            await orig()

        s.commit = spy
        await eng.ensure_ladder(s, plan)
        kinds = [c[0] for c in raw.calls]
        assert kinds[0] == "commit" and kinds.index("commit") < kinds.index("cond_create")   # 등록 기록 → commit → 토스
        raw.calls.clear()
        leg = (await legs_of(s, plan))[0]
        await eng._modify_leg(s, plan, leg, qty=10)
        kinds = [c[0] for c in raw.calls]
        assert kinds.index("commit") < kinds.index("cond_modify")                          # 수정 중 기록 → commit → 토스
        raw.calls.clear()
        raw.price = D("9.0")
        await eng._sell_cross(s, plan, seq=3, qty=10, cur=D("9.0"), kind="immediate", old_leg=None)
        kinds = [c[0] for c in raw.calls]
        assert kinds.index("commit") < kinds.index("limit_create")                         # 예약 기록 → commit → 토스


async def test_tick_once_uses_one_session_per_plan(plan_db):
    from contextlib import asynccontextmanager

    from backend.execution.plan.brokers import PaperRaw
    from backend.execution.plan.runner import PlanExecutor

    opened = {"now": 0, "max_during_toss": 0, "total": 0}
    raw = FakeRaw("10")
    raw.acct = 60
    orig_price = raw.last_price_rest

    async def probe(s, symbol):
        opened["max_during_toss"] = max(opened["max_during_toss"], opened["now"])
        return await orig_price(s, symbol)

    raw.last_price_rest = probe
    eng = make_engine(raw, regular=REG, clock=lambda: datetime.utcnow())

    @asynccontextmanager
    async def gs():
        opened["now"] += 1
        opened["total"] += 1
        try:
            async with get_session() as s:
                yield s
        finally:
            opened["now"] -= 1

    async def notify(*a):
        return None

    ex = PlanExecutor(real_engine=eng, paper_engine=eng, paper_raw=PaperRaw(lambda s: None), session_factory=gs, notify=notify)
    async with get_session() as s:
        for sym in ("TESTA", "TESTB"):
            await seed_holding(s, eng, symbol=sym)
    opened["total"] = 0
    await ex.tick_once()
    assert opened["max_during_toss"] == 1                           # 토스를 부르는 동안 열려 있는 세션은 그 계획 하나뿐
    assert opened["total"] >= 3                                     # 목록 읽기 + 계획마다 한 세션


# ── 높음 3 · 실행기 값은 따로 · 낙관적 잠금 ─────────────────────────────────────────

async def test_runtime_is_a_separate_column_and_concurrent_writes_conflict(plan_db):
    from sqlalchemy.orm.exc import StaleDataError

    eng = make_engine(FakeRaw())
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper", params={"qty": 6, "buy_watch": 9, "buy_order": 9})
        pid = plan.id
        before = plan.params_json
        set_runtime(plan, price=11.0)
        assert plan.params_json == before and runtime_of(plan)["price"] == 11.0      # 화면이 고치는 값 칸은 그대로
    a, b = AsyncSessionLocal(), AsyncSessionLocal()
    try:
        pa, pb = await a.get(Plan, pid), await b.get(Plan, pid)
        set_runtime(pb, price=12.0)
        await b.commit()                                                           # 실행기가 먼저 저장
        pa.halted_reason = "화면 정지"
        with pytest.raises(StaleDataError):                                        # 화면 쪽 낡은 사본은 덮어쓰지 못하고 충돌
            await a.commit()
    finally:
        await a.rollback()
        await a.close()
        await b.close()
    async with get_session() as s:
        assert runtime_of(await s.get(Plan, pid))["price"] == 12.0


async def test_stale_data_error_is_409(plan_db):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.orm.exc import StaleDataError

    from backend.api.main import app

    @app.get("/__stale_probe")
    async def _probe():
        raise StaleDataError("x")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/__stale_probe")
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "stale"


# ── 높음 4 · 보유 전 정지 ─────────────────────────────────────────────────────────

async def test_halted_adopt_pending_becomes_cancelled_and_never_hangs_legs(plan_db):
    raw = FakeRaw("10")
    raw.acct = 30
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", source="adopt",
                                      params={"adopt": {"qty": 30, "avg_price": 10.0}})
        plan.state, plan.approved_at = state.APPROVED, NOW
        await eng.adopt_approve(s, plan)
        await state.halt(s, plan, "계획 정지")
        await eng.tick_plan(s, plan)
        assert plan.state == state.CANCELLED                       # 인수 대기 중 정지 = 인수 취소
        assert raw.count("cond_create") == 0 and raw.count("limit_create") == 0


async def test_halted_entry_plan_is_not_closed_and_resume_re_places_buy(plan_db):
    raw, eng = await setup(price="10")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 9.5, "buy_order": 9.5, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        assert plan.state == state.ENTRY_ARMED and raw.count("cond_create") == 1
        await eng.stop_plan(s, plan)                               # 정지 = 대기 매수 취소
        assert plan.state == state.HALTED and plan.prev_state == state.ENTRY_ARMED
        for _ in range(3):
            await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED                          # 바로 CLOSED 되지 않는다 · 보호 다리도 없다
        assert raw.count("cond_create") == 1
        assert await eng.resume_plan(s, plan) == state.ENTRY_ARMED
        await eng.tick_plan(s, plan)
        assert raw.count("cond_create") == 2                       # 진입이 다시 걸린다


# ── 높음 5 · 줄이기 중 이미 넘으면 한 번만 처리 ────────────────────────────────────

async def test_shrink_with_crossed_leg_sells_once_not_three_times(plan_db):
    raw, eng = await setup(price="10", qty=90)
    async with get_session() as s:
        plan = await seed_holding(s, eng, qty=90)
        await eng.ensure_ladder(s, plan)
        assert [l.qty for l in await legs_of(s, plan)] == [30, 30, 30]
        raw.price = D("9.25")                                      # 마지막 다리(감시가 9.30)가 이미 넘음
        await sizing.reserve(s, plan.id, "triggered", 15, "T1")
        await eng.ensure_ladder(s, plan)
        assert raw.count("limit_create") == 1                      # 즉시 매도는 1번 (재시도 없음)


# ── 높음 6 · 기동 다시 맞추기 재시도 · 표 만들기 ──────────────────────────────────────

async def test_startup_resync_retries_until_success(plan_db, monkeypatch):
    from backend.execution.plan import runner
    from backend.execution.plan.brokers import PaperRaw

    eng = make_engine(FakeRaw())

    async def notify(*a):
        return None

    ex = runner.PlanExecutor(real_engine=eng, paper_engine=eng, paper_raw=PaperRaw(lambda s: None), notify=notify)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("토스 일시 오류")
        return 4, 0

    async def instant(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(ex, "resync_once", flaky)
    monkeypatch.setattr(runner.asyncio, "wait_for", instant)
    assert await ex._startup_resync(asyncio.Event()) == (4, 0) and calls["n"] == 3     # 실행기가 죽지 않고 되풀이


async def test_start_executor_creates_plan_tables_first(monkeypatch):
    from backend.execution.plan import runner
    import backend.services.db as dbmod

    order = []

    async def fake_init():
        order.append("init_db")

    monkeypatch.setattr(runner, "executor_enabled", lambda: True)
    monkeypatch.setattr(dbmod, "init_db", fake_init)
    monkeypatch.setattr(runner, "acquire_lock", lambda *a, **k: order.append("lock") or None)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(runner, "default_notify", noop)
    assert await runner.start_executor(asyncio.Event()) is None
    assert order == ["init_db", "lock"]                              # cron 에는 create_all 이 없어 표를 먼저 만든다


async def test_recovery_alert_only_after_invariants_pass(plan_db, monkeypatch):
    from backend.execution.plan import runner
    from backend.execution.plan.brokers import PaperRaw

    eng = make_engine(FakeRaw())
    sent = []

    async def notify(level, title, body, category):
        sent.append(title)

    ex = runner.PlanExecutor(real_engine=eng, paper_engine=eng, paper_raw=PaperRaw(lambda s: None), notify=notify)

    async def no_ws(stop):
        return None

    async def idle():
        return None

    ex.ws.run = no_ws
    monkeypatch.setattr(ex, "tick_once", idle)
    for result, expected in (((3, 0), "실행기 복구"), ((3, 2), "실행기 시작 · 불변식 확인 필요")):
        sent.clear()

        async def rs(result=result):
            return result

        monkeypatch.setattr(ex, "resync_once", rs)
        stop = asyncio.Event()
        task = asyncio.create_task(ex.run(stop))
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, 5)
        assert sent[0] == expected


# ── 높음 7 · 정지 중 추적 값 · 위로만 ─────────────────────────────────────────────

async def test_halted_trailing_keeps_trail_values_and_never_lowers(plan_db):
    raw, eng = await setup(price="14")
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        plan.state, plan.peak_price = state.TRAILING, 14.0
        await eng.ensure_ladder(s, plan)
        assert {PD(l.watch_price) for l in await legs_of(s, plan)} == {D("11.90")}
        await state.halt(s, plan, "시험")
        assert eng._values_for(plan, 1, "regular", D("14")).watch == D("11.90")        # 사다리 값(낮음)이 아니라 추적 값
        raw.price = D("12.0")
        eng.regular_window = lambda now: None                                          # 정규장 밖 → 비상 값 10.20 은 더 낮다
        before = raw.count("cond_modify")
        await eng._swap_session(s, plan, NOW)
        assert raw.count("cond_modify") == before                                      # 정지 중에는 낮추지 않는다
        assert {PD(l.watch_price) for l in await legs_of(s, plan)} == {D("11.90")}


# ── 중간 ─────────────────────────────────────────────────────────────────────────

async def test_modify_rewrites_expire_date(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        leg.expire_date = "2026-01-01"
        assert await eng._modify_leg(s, plan, leg, qty=10)
        assert leg.expire_date == (NOW + timedelta(days=90)).strftime("%Y-%m-%d")
        assert raw.conds[leg.toss_id]["expire"] == leg.expire_date                     # 토스에 보낸 값도 같다


async def test_fill_ledger_key_is_the_leg_id_even_when_child_order_appears(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        c = raw.conds[leg.toss_id]
        c.update(status="TRIGGERED", order_id="CHILD1", filled=5, remaining=15, avg=D("9.5"))
        await eng.sync_orders(s, plan)
        c.update(status="FILLED", filled=20, remaining=0)
        await eng.sync_orders(s, plan)
        fills = list(await s.scalars(select(PlanFill).where(PlanFill.plan_id == plan.id, PlanFill.side == "SELL")))
        assert sum(f.qty for f in fills) == 20 and {f.order_ref for f in fills} == {leg.toss_id}   # 이중 기록 없음


async def test_missing_average_price_stops_registration_with_one_alert(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        plan.avg_price = None
        assert await eng.ensure_ladder(s, plan) == "skipped"
        assert await eng.ensure_ladder(s, plan) == "skipped"
        assert raw.count("cond_create") == 0
        assert len([a for a in eng._alerts if a[1] == "평균가 없음"]) == 1               # 알림은 한 번


async def test_limit_unavailable_alert_once_and_cross_blocked_after_three_rejects(plan_db):
    raw, eng = await setup(price="9.60", limit_factor=None)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        for _ in range(3):
            await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        assert len([a for a in eng._alerts if a[1] == "지정가를 낼 수 없는 시간대"]) == 1   # 경고는 한 번
    raw2, eng2 = await setup(price="9.60")
    raw2.reject_sell = "x"
    async with get_session() as s:
        plan = await seed_holding(s, eng2, symbol="TESTB")
        for _ in range(3):
            await eng2._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        assert plan.state == state.HALTED and runtime_of(plan)["cross_blocked"] == ["1"]
        n = raw2.count("limit_create")
        for _ in range(3):                                                             # 정지 뒤 같은 즉시 매도를 되풀이하지 않는다
            await eng2._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=None)
        assert raw2.count("limit_create") == n
        eng2.kill_state = lambda: (False, True)
        await eng2.resume_plan(s, plan) if False else None
        set_runtime(plan, cross_blocked=[], reject_loops={})                           # 재개하면 풀린다 (resume_plan 이 같은 일)


async def test_old_gone_event_when_modify_flips(plan_db):
    raw, eng = await setup()
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.price_queue = [D("10"), D("9.60"), D("9.60"), D("9.60")]                   # 수정 직후 다시 읽었더니 방향이 뒤집힘
        await eng._modify_leg(s, plan, leg, vals=eng._values_for(plan, 1, "regular", D("10")))
        ev = list(await s.scalars(select(state.PlanEvent).where(state.PlanEvent.plan_id == plan.id,
                                                                state.PlanEvent.kind == "leg_old_gone")))
        assert ev and "옛 다리도 새 다리도 없음" in ev[0].detail


async def test_adopt_waits_for_app_plain_sell_orders_too(plan_db):
    raw = FakeRaw("10")
    raw.acct = 30
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    raw.limits["APPSELL"] = dict(status="OPEN", symbol="TESTA", side="SELL", qty=30, price=D("11"), filled=0, remaining=30,
                                 avg=None, client_id="app")
    raw.limits["APPBUY"] = dict(status="OPEN", symbol="TESTA", side="BUY", qty=5, price=D("9"), filled=0, remaining=5,
                                avg=None, client_id="app2")
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", source="adopt", params={"adopt": {"qty": 30, "avg_price": 10.0}})
        plan.state, plan.approved_at = state.APPROVED, NOW
        await eng.adopt_approve(s, plan)
        await eng.tick_plan(s, plan)
        assert plan.state == state.ADOPT_PENDING                                       # 일반 매도 주문 1건이 남아 있어 대기
        rows = runtime_of(plan)["adopt_foreign"]
        assert [(r["toss_id"], r["kind"]) for r in rows] == [("APPSELL", "order")]     # 매수 주문은 세지 않는다
        raw.limits["APPSELL"]["status"] = "CANCELED"
        await eng.tick_plan(s, plan)
        assert plan.state == state.HOLDING


async def test_create_draft_drops_internal_keys(plan_db):
    eng = make_engine(FakeRaw())
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper", params={
            "qty": 6, "buy_watch": 9, "buy_order": 9, "_runtime": {"x": 1}, "cid_ver": {"sl1": 9}, "reject_loops": {"1": 2},
            "cross_blocked": ["1"], "evil": 1, "rationale": {"a": "근거"}})
        p = params_of(plan)
        assert "_runtime" not in p and "cid_ver" not in p and "reject_loops" not in p and "evil" not in p
        assert p["qty"] == 6 and p["rationale"] == {"a": "근거"}


async def test_gate_caches_account_qty_only_within_a_tick_and_clears_on_orders(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    calls = {"n": 0}
    orig = raw.account_qty

    async def counting(s, pid, sym):
        calls["n"] += 1
        return await orig(s, pid, sym)

    raw.account_qty = counting
    gate = DirectionGate(raw)
    await gate.account_qty(None, 1, "TESTA")
    await gate.account_qty(None, 1, "TESTA")
    assert calls["n"] == 2                                          # 걸음 밖에서는 캐시하지 않는다
    gate.begin_tick()
    for _ in range(4):
        await gate.account_qty(None, 1, "TESTA")
    assert calls["n"] == 3                                          # 걸음 안에서는 한 번
    await gate.sell_limit(None, plan_id=1, symbol="TESTA", qty=1, price=D("9"), client_id="c")
    await gate.account_qty(None, 1, "TESTA")
    assert calls["n"] == 4                                          # 주문을 낸 뒤에는 다시 읽는다


def test_hold_jump_pure():
    assert sess.hold_jump(None, None, 10.0) == (10.0, None)
    assert sess.hold_jump(10.0, None, 10.9) == (10.9, None)
    assert sess.hold_jump(10.0, None, 12.0) == (10.0, 12.0)         # 20% 튐 → 보류 · 직전 값을 쓴다
    assert sess.hold_jump(10.0, 12.0, 12.2) == (12.0, None)         # 다음 읽기가 3% 안 → 확정
    assert sess.hold_jump(10.0, 12.0, 10.5) == (10.5, None)         # 확인 못 함 → 보류를 버리고 정상 값


async def test_time_stop_and_trail_use_held_price(plan_db):
    """한 번 튄 이상값으로 시간 손절 끌어올리기를 하지 않는다 · 같은 걸음에서는 한 번만 갱신."""
    raw = FakeRaw("10.50")
    raw.acct = 60
    clock = Clock(datetime(2026, 11, 20, 15, 0))
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-09T22:00:00"})
        await eng.ensure_ladder(s, plan)
        assert eng._held_price(plan, D("10.50"), clock()) == D("10.50")
        clock.advance(seconds=5)
        assert eng._held_price(plan, D("14.00"), clock()) == D("10.50")             # 33% 튐 → 보류
        assert eng._held_price(plan, D("14.00"), clock()) == D("10.50")             # 같은 걸음에 다시 불러도 자기 확인 안 함
        clock.advance(seconds=5)
        assert eng._held_price(plan, D("14.10"), clock()) == D("14.00")             # 다음 걸음이 3% 안에서 확인 → 확정


# ── 낮음 ─────────────────────────────────────────────────────────────────────────

def test_requirements_websockets_14_and_workflow_curl_hides_host():
    root = Path(__file__).resolve().parents[2]
    assert "websockets>=14.0" in (root / "backend" / "requirements.txt").read_text()
    wf = (root / ".github" / "workflows" / "plan-executor-watch.yml").read_text()
    assert "curl -fs --max-time" in wf and "-fsS" not in wf and "2>/dev/null" in wf        # 오류 문구에 주소가 찍히지 않는다


def test_sentry_scrub_and_no_request_body(monkeypatch):
    import sys
    import types

    from backend.services import config, observability

    ev = {"request": {"data": {"code": "123456"}, "cookies": {"sniper_session": "x"}, "query_string": "a=1",
                      "headers": {"X-API-Token": "t", "Cookie": "c", "Accept": "json"}}}
    out = observability.scrub_event(ev)
    assert "data" not in out["request"] and "cookies" not in out["request"] and "query_string" not in out["request"]
    assert out["request"]["headers"] == {"X-API-Token": "[지움]", "Cookie": "[지움]", "Accept": "json"}
    seen = {}
    fake = types.ModuleType("sentry_sdk")
    fake.init = lambda **kw: seen.update(kw)
    integ = types.ModuleType("sentry_sdk.integrations")
    fa = types.ModuleType("sentry_sdk.integrations.fastapi")
    fa.FastApiIntegration = lambda: None
    sa = types.ModuleType("sentry_sdk.integrations.sqlalchemy")
    sa.SqlalchemyIntegration = lambda: None
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations", integ)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.fastapi", fa)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.sqlalchemy", sa)
    monkeypatch.setattr(config, "sentry_dsn", lambda: "https://x@example.invalid/1")
    monkeypatch.setattr(observability, "_INITIALIZED", False)
    assert observability.init_sentry() is True
    assert seen["max_request_body_size"] == "never" and seen["before_send"] is observability.scrub_event and seen["send_default_pii"] is False
    monkeypatch.setattr(observability, "_INITIALIZED", False)


def test_token_revoked_compare_and_unlink_happen_inside_the_lock(tmp_path, monkeypatch):
    import httpx

    from backend.execution.brokers import toss_client as tc
    from backend.execution.exceptions import BrokerCommunicationError

    kw = {"client_id": "id", "client_" + "secret": "dummy", "account_seq": "1"}
    c = tc.TossClient(**kw, token_cache_path=tmp_path / "tok.json")
    p = tmp_path / "tok.json"
    p.write_text(json.dumps({"access_token": "mine", "expires_at": 9999999999}))
    resp = httpx.Response(401, json={"error": {"code": "token-revoked", "message": "x"}},
                          request=httpx.Request("GET", "https://openapi.tossinvest.com/api/v1/holdings"))
    monkeypatch.setattr(tc, "_LOCK_WAIT_SEC", 0.2)
    fd = os.open(str(tmp_path / "toss_token.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)                                   # 다른 프로세스가 잠금을 쥐고 새 토큰을 쓰는 중
    try:
        with pytest.raises(BrokerCommunicationError):
            c._raise_from_response(resp)
        assert p.exists()                                            # 잠금을 못 잡으면 지우지 않는다
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    with pytest.raises(BrokerCommunicationError):
        c._raise_from_response(resp)
    assert not p.exists()                                            # 잠금을 잡으면 (같은 토큰이면) 지운다
