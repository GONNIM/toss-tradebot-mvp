"""1116-01 · 가격 · 시간대 · 수량 불변식 · 상태 기계 · 하트비트 · 다시 맞추기 · 자동 초안 시험 (실제 호출 0)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.execution.plan import drafts, heartbeat, resync, sessions as sess, sizing, state
from backend.execution.plan import pricing as pr
from backend.execution.plan.models import PlanLeg, PlanLegPending, PlanExecutorHeartbeat
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401

D = Decimal


# ── 가격 규칙 ──────────────────────────────────────────────────

def test_tick_sizes_and_rounding_directions():
    assert pr.tick("0.9999") == D("0.0001") and pr.tick("1.00") == D("0.01")
    assert pr.buy_watch("9.456") == D("9.45") and pr.buy_order("9.459") == D("9.45")        # 매수: 둘 다 내림
    assert pr.sell_watch("9.451") == D("9.46") and pr.sell_order("9.459") == D("9.45")      # 매도: 감시 올림 · 주문 내림
    assert pr.sell_watch("0.50001") == D("0.5001") and pr.sell_order("0.50009") == D("0.5000")


@pytest.mark.parametrize("price,watch", [("1.00", "0.98"), ("1.50", "1.48"), ("1.99", "1.97"), ("2.00", "1.98")])
def test_lift_step1_is_a_stop_not_an_immediate_sell_at_boundaries(price, watch):
    """끌어올리기 1단계 경계: 현재가 1.00 · 1.50 · 1.99 · 2.00 에서 조건주문으로 걸린다 (즉시 매도 아님)."""
    v = sess.lift_values(price)
    assert v.watch == D(watch)
    assert pr.below_by_tick(v.watch, price)
    assert v.order == pr.floor_tick(D(price) * D("0.98"))


def test_direction_boundaries_one_tick():
    assert pr.below_by_tick("9.99", "10.00") and not pr.below_by_tick("10.00", "10.00")
    assert pr.above_by_tick("10.01", "10.00") and not pr.above_by_tick("10.00", "10.00")
    assert pr.cap_sell_watch("9.99", "10.00") == D("9.98")                  # min(계산값, 현재가 − 2틱)


def test_qty_multiple_of_six_floor():
    assert pr.qty_for_budget(100, 10) == 6                                  # 100/(10.01)=9.99 → 9 → 6 의 배수 6
    assert pr.qty_for_budget(1000, 10) == 96 and pr.qty_for_budget(0, 10) == 0


def test_caps_default_zero_means_no_order(monkeypatch):
    for k in ("PLAN_MAX_ORDER_USD", "PLAN_TOTAL_CAP_USD", "PLAN_TEST_MAX_USD"):
        monkeypatch.delenv(k, raising=False)
    assert "상한" in pr.check_caps(mode="live", order_usd=1, open_total_usd=0)
    assert "상한" in pr.check_caps(mode="test", order_usd=1, open_total_usd=0)
    assert pr.check_caps(mode="paper", order_usd=10 ** 9, open_total_usd=0) is None
    monkeypatch.setenv("PLAN_TEST_MAX_USD", "50")
    assert pr.check_caps(mode="test", order_usd=50, open_total_usd=0) is None
    assert pr.check_caps(mode="test", order_usd=51, open_total_usd=0)


# ── 시간대 ─────────────────────────────────────────────────────

def test_leg_session_swap_one_minute_after_open_and_close():
    reg = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))
    assert sess.leg_session(datetime(2026, 11, 20, 14, 30, 59), reg) == "off"
    assert sess.leg_session(datetime(2026, 11, 20, 14, 31), reg) == "regular"
    assert sess.leg_session(datetime(2026, 11, 20, 21, 0, 59), reg) == "regular"
    assert sess.leg_session(datetime(2026, 11, 20, 21, 1), reg) == "off"
    assert sess.leg_session(datetime(2026, 11, 20, 12, 0), None) == "off"


def test_peak_holds_ten_percent_jump_until_confirmed():
    peak, pend = sess.update_peak(None, None, 10.0)
    assert (peak, pend) == (10.0, None)
    peak, pend = sess.update_peak(peak, pend, 11.5)                         # 15% 튐 → 보류
    assert (peak, pend) == (10.0, 11.5)
    assert sess.update_peak(peak, pend, 11.4) == (11.5, None)               # 다음 종가가 3% 안 → 확정
    assert sess.update_peak(peak, pend, 10.2) == (10.2, None)               # 확인 못 함 → 보류 버리고 정상 갱신
    assert sess.update_peak(10.0, None, 10.9) == (10.9, None)


def test_trail_min_step_and_values():
    assert sess.trail_values(10, 14).watch == D("11.90")
    assert sess.trail_min_step("1.00") == D("0.005") and sess.trail_min_step("20") == D("0.10")
    assert sess.trail_should_raise("20", "20.10") and not sess.trail_should_raise("20", "20.05")


def test_trading_days_and_timestop_window():
    assert sess.add_trading_days(date(2026, 11, 9), 5) == date(2026, 11, 16)
    assert sess.add_trading_days(date(2026, 11, 20), 1, frozenset({date(2026, 11, 23)})) == date(2026, 11, 24)
    assert sess.timestop_due(datetime(2026, 11, 9, 22), datetime(2026, 11, 17, 15))
    assert not sess.timestop_due(datetime(2026, 11, 13, 22), datetime(2026, 11, 17, 15))
    w = sess.timestop_window((datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0)))
    assert (w.lift_from.hour, w.lift_from.minute) == (15, 0)
    assert (w.clean_from.hour, w.clean_from.minute) == (20, 30)
    assert (w.cancel_at.hour, w.cancel_at.minute) == (20, 59)


# ── 불변식 순수 함수 ──────────────────────────────────────────

def test_invariants_pure():
    assert sizing.split_ladder(60) == [20, 20, 20] and sizing.split_ladder(62) == [20, 20, 22]
    assert sizing.split_ladder(2) == [2] and sizing.split_ladder(0) == []
    assert sizing.sl_target(60, 20) == 40 and sizing.tp1_cap(60, 20) == 20 and sizing.tp1_cap(61, 0) == 30
    assert sizing.must_use_tp1_watch(70, 60) and not sizing.must_use_tp1_watch(60, 60)
    assert sizing.check_invariants(base=60, accepted_sell=0, sl_qtys=[20, 20, 20]).status == "ok"
    assert sizing.check_invariants(base=60, accepted_sell=0, sl_qtys=[20, 20]).status == "shortage"
    assert sizing.check_invariants(base=60, accepted_sell=20, sl_qtys=[20, 20, 20]).delta == 20
    assert sizing.check_invariants(base=60, accepted_sell=0, sl_qtys=[20, 20, 20], dup_pairs=True).status == "excess"


# ── 상태 기계 ──────────────────────────────────────────────────

def test_transitions():
    ok = [("DRAFT", "APPROVED"), ("APPROVED", "ENTRY_ARMED"), ("ENTRY_ARMED", "ENTRY_RETRY"), ("ENTRY_RETRY", "CANCELLED"),
          ("HOLDING", "TP1_WAIT"), ("HOLDING", "TRAILING"), ("TRAILING", "CLOSED"), ("ADOPT_PENDING", "TRAILING"),
          ("HOLDING", "HALTED"), ("HALTED", "HOLDING")]
    bad = [("DRAFT", "HOLDING"), ("CLOSED", "HOLDING"), ("CANCELLED", "HALTED"), ("TRAILING", "HOLDING"),
           ("ENTRY_ARMED", "TRAILING")]
    assert all(state.can_transition(a, b) for a, b in ok)
    assert not any(state.can_transition(a, b) for a, b in bad)


async def test_halt_and_resume_return_to_previous_state(plan_db):
    raw = FakeRaw()
    raw.acct = 60
    eng = make_engine(raw)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        assert await state.halt(s, plan, "시험")
        assert plan.state == state.HALTED and plan.prev_state == state.HOLDING
        assert not await state.halt(s, plan, "again")
        assert await state.resume(s, plan) == state.HOLDING


async def test_resume_requires_invariants_to_pass(plan_db):
    raw = FakeRaw()
    raw.acct = 60
    eng = make_engine(raw, regular=(datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0)), clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        await state.halt(s, plan, "시험")
        assert await eng.resume_plan(s, plan) == state.HOLDING


# ── 하트비트 ───────────────────────────────────────────────────

async def test_heartbeat_stale_alert_once_and_recovery(plan_db):
    sent = []

    async def send(title, body):
        sent.append(title)
        return True

    t0 = datetime(2026, 11, 20, 15, 0, 0)
    async with get_session() as s:
        assert await heartbeat.check_stale(s, send, t0) is False            # 기록 없음
        await heartbeat.write(s, ws_status="none", now=t0)
        assert await heartbeat.check_stale(s, send, t0 + timedelta(seconds=119)) is False
        assert await heartbeat.check_stale(s, send, t0 + timedelta(seconds=121)) is True
        assert await heartbeat.check_stale(s, send, t0 + timedelta(seconds=200)) is False   # 같은 끊김에 반복 안 함
        assert sent == ["실행기 끊김"]
        await heartbeat.write(s, now=t0 + timedelta(seconds=210))             # 복구
        assert await heartbeat.check_stale(s, send, t0 + timedelta(seconds=500)) is True    # 새 끊김은 다시 알림
        assert await heartbeat.age_seconds(s, t0 + timedelta(seconds=240)) == 30
        await heartbeat.notify_recovered(s, send, 3)
        assert sent[-1] == "실행기 복구"


# ── 다시 맞추기 ────────────────────────────────────────────────

REG = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))


async def _ladder(s, raw, eng, **kw):
    plan = await seed_holding(s, eng, **kw)
    await eng.ensure_ladder(s, plan)
    legs = list(await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING").order_by(PlanLeg.seq)))
    return plan, legs


async def test_resync_links_new_order_from_pending_record_without_duplicates(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan, legs = await _ladder(s, raw, eng)
        leg = legs[0]
        old = leg.toss_id
        # 수정 도중 멈춤: 옛 번호는 취소됐고 새 주문이 걸렸으나 장부에는 옛 번호가 남음
        raw.conds[old]["status"] = "CANCELED"
        await raw.cond_create(s, plan_id=plan.id, symbol="TESTA", side="SELL", qty=20, watch=D("8.5"), order=D("8.24"),
                              client_id="cid-new", expire="2027-01-01")
        s.add(PlanLegPending(leg_id=leg.id, plan_id=plan.id, old_toss_id=old, new_watch=8.5, new_order=8.24, qty=20,
                             client_order_id="cid-new"))
        await s.flush()
        before = len(raw.conds)
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["pending"]["linked"] == 1 and len(raw.conds) == before     # 중복 등록 0
        assert leg.toss_id != old and leg.watch_price == 8.5
        assert (await s.scalars(select(PlanLegPending))).first() is None


async def test_resync_excludes_already_linked_numbers_and_halts_on_multiple(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan, legs = await _ladder(s, raw, eng)
        leg = legs[0]
        old = leg.toss_id
        # 같은 값의 후보가 둘: 하나는 이미 다른 다리(legs[1])에 이어진 번호 → 빼면 후보 1개
        other = legs[1]
        raw.conds[other.toss_id].update(qty=20, watch=D("8.5"), order=D("8.24"))
        other.qty, other.watch_price, other.order_price = 20, 8.5, 8.24
        await raw.cond_create(s, plan_id=plan.id, symbol="TESTA", side="SELL", qty=20, watch=D("8.5"), order=D("8.24"),
                              client_id="x", expire="2027-01-01")
        raw.conds[old]["status"] = "CANCELED"
        s.add(PlanLegPending(leg_id=leg.id, plan_id=plan.id, old_toss_id=old, new_watch=8.5, new_order=8.24, qty=20,
                             client_order_id="nomatch"))
        await s.flush()
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["pending"]["linked"] == 1 and plan.state == state.HOLDING
        # 후보가 여럿이면 넘침 → HALTED
        raw2 = FakeRaw("10")
        raw2.acct = 60
        eng2 = make_engine(raw2, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
        plan2, legs2 = await _ladder(s, raw2, eng2, symbol="TESTB")
        l2 = legs2[0]
        raw2.conds[l2.toss_id]["status"] = "CANCELED"
        for i in range(2):
            await raw2.cond_create(s, plan_id=plan2.id, symbol="TESTB", side="SELL", qty=20, watch=D("8.5"),
                                   order=D("8.24"), client_id=f"d{i}", expire="2027-01-01")
        s.add(PlanLegPending(leg_id=l2.id, plan_id=plan2.id, old_toss_id=l2.toss_id, new_watch=8.5, new_order=8.24,
                             qty=20, client_order_id="none"))
        await s.flush()
        await resync.resync_plan(s, eng2, plan2)
        assert plan2.state == state.HALTED


async def test_resync_old_and_new_both_missing_hangs_protection_again(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan, legs = await _ladder(s, raw, eng)
        leg = legs[0]
        raw.conds[leg.toss_id]["status"] = "CANCELED"
        s.add(PlanLegPending(leg_id=leg.id, plan_id=plan.id, old_toss_id=leg.toss_id, new_watch=8.5, new_order=8.24,
                             qty=20, client_order_id="zzz"))
        await s.flush()
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["pending"]["lost"] == 1
        live = list(await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING", PlanLeg.role == "sl")))
        assert sum(l.qty for l in live) == 60


async def test_resync_old_alive_keeps_old_value_and_retries(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan, legs = await _ladder(s, raw, eng)
        leg = legs[0]
        s.add(PlanLegPending(leg_id=leg.id, plan_id=plan.id, old_toss_id=leg.toss_id, new_watch=8.5, new_order=8.24,
                             qty=20, client_order_id="zzz"))
        await s.flush()
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["pending"]["retry"] == 1 and leg.tag == ""
        assert leg.watch_price == 9.7                                          # 옛 값 그대로


async def test_resync_extends_near_expiry_and_flags_foreign_overlap(plan_db):
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(datetime(2026, 11, 20, 15)))
    async with get_session() as s:
        plan, legs = await _ladder(s, raw, eng)
        legs[0].expire_date = "2026-11-25"                                    # 10일 아래
        rep = await resync.resync_plan(s, eng, plan)
        assert rep.get("extended") == 1 and raw.count("cond_modify") >= 1
        raw.conds["APP"] = dict(id="APP", status="WATCHING", symbol="TESTA", side="SELL", qty=10, watch=D("9"),
                                order=D("8.9"), client_id="app", order_id=None, filled=0, remaining=10, avg=None)
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["ok"] is False and any(a[0] == "critical" for a in eng._alerts)


# ── 자동 초안 ─────────────────────────────────────────────────

def test_draft_radar_gate_uses_file_name_date(tmp_path):
    today = date(2026, 11, 20)
    assert drafts.radar_ready(tmp_path, today) is False                       # 파일 없음
    (tmp_path / "radar_v1_3_20261119.csv").write_text("x")
    assert drafts.radar_ready(tmp_path, today) is False                       # 어제 날짜
    f = tmp_path / "radar_v1_3_20261120.csv"
    f.write_text("x")
    assert drafts.radar_ready(tmp_path, today) is True
    import os
    os.utime(f, (0, 0))                                                       # 수정 시각은 보지 않는다
    assert drafts.radar_ready(tmp_path, today) is True
    assert drafts.radar_ready(None, today) is False


def test_draft_attempt_schedule_and_values():
    n = [drafts.attempt_number(datetime(2026, 11, 20, h, m, tzinfo=drafts._KST)) for h, m in
         ((7, 15), (7, 25), (7, 35), (7, 45), (7, 55), (8, 5), (7, 20))]
    assert n == [1, 2, 3, 4, 5, 6, None] and drafts.MAX_ATTEMPTS == 6
    p = drafts.build_draft_params(ref_price="9.459", budget_usd=1000, announce_at=datetime(2026, 11, 24, 22),
                                  entry_close_at=datetime(2026, 11, 24, 21), entry_window_end=datetime(2026, 11, 27, 21),
                                  tp1_pct="0.2")
    assert p["buy_watch"] == 9.45 and p["buy_order"] == 9.45 and p["qty"] % 6 == 0
    assert p["ladder_pcts"] == [0.03, 0.05, 0.07]                              # 기본 폭 · 넓은 폭은 제안으로만


async def test_job_plan_draft_waits_then_warns_once_at_last_attempt(plan_db, monkeypatch, tmp_path):
    from backend.execution.plan import runner

    warned = []

    async def fake_notify(level, title, body, category):
        warned.append((level, title, category))

    monkeypatch.setattr(runner, "default_notify", fake_notify)
    monkeypatch.setenv("PLAN_RADAR_DIR", str(tmp_path))                        # 파일 없음
    kst = drafts._KST
    def utc(h, m, day=20):
        return datetime(2026, 11, day, h, m, tzinfo=kst).astimezone(timezone.utc).replace(tzinfo=None)
    assert await runner.job_plan_draft(utc(7, 15)) == "wait"
    assert await runner.job_plan_draft(utc(8, 5)) == "warned"
    assert warned == [("warning", "자동 초안 없음", "system")]
    assert await runner.job_plan_draft(utc(8, 5)) == "skip"                    # 그날은 한 번만
    (tmp_path / "radar_v1_3_20261121.csv").write_text("x")
    assert await runner.job_plan_draft(utc(7, 15, 21)) == "no_rule"   # 규칙 미구현 · 후보 0


# ── 실행기 시작 조건 ───────────────────────────────────────────

async def test_executor_does_not_start_without_issue_key(monkeypatch, tmp_path, caplog):
    import asyncio
    from backend.execution.plan import runner

    monkeypatch.delenv("TOSS_TOKEN_ISSUE", raising=False)
    monkeypatch.setattr(runner, "executor_enabled", runner.executor_enabled)
    from backend.services import config
    monkeypatch.setattr(config, "get", lambda name, default=None: None if name == "TOSS_TOKEN_ISSUE" else default)
    assert runner.executor_enabled() is False
    called = []
    monkeypatch.setattr(runner, "acquire_lock", lambda *a, **k: called.append(1) or 5)
    assert await runner.start_executor(asyncio.Event()) is None and called == []


async def test_executor_lock_allows_only_one(tmp_path):
    from backend.execution.plan import runner

    p = tmp_path / "plan_executor.lock"
    fd = runner.acquire_lock(p)
    assert fd is not None
    assert runner.acquire_lock(p) is None
    import os
    os.close(fd)
    fd2 = runner.acquire_lock(p)
    assert fd2 is not None
    os.close(fd2)
