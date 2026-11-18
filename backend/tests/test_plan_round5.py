"""1116-01 · 5차 검토 재현 시험 (가짜 브로커 · 가상 종목 · 실제 호출 0).

모든 시험은 끝에서 「토스에 걸린 매도 합 <= 보유」 를 확인한다 (check_sells).
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

from sqlalchemy import select

from backend.execution.plan import orderbook as ob
from backend.execution.plan import resync, state
from backend.execution.plan.engine import runtime_of
from backend.execution.plan.models import PlanFill, PlanLeg, PlanOrderBook, PlanSellReservation
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401
from backend.tests.test_plan_api import OK_ORIGIN, api, cookie, hdr, mk_plan  # noqa: F401
from backend.tests.test_plan_orderbook import (  # noqa: F401
    NOW, REG, _api_line, _clean_env, _entry, cfg, legs_of, lines, setup, unknown_leg)

D = Decimal


def live_sells(raw):
    return sum(c["qty"] for c in raw.conds.values() if c["status"] == "WATCHING" and c["side"] == "SELL")


def check_sells(raw):
    assert live_sells(raw) <= raw.acct, f"토스 매도 합 {live_sells(raw)} > 보유 {raw.acct}"


async def known_open(s, plan, raw):
    """계획이 아는 번호(다리 · 장부 줄)로 아직 토스에 열려 있는 주문 수."""
    ids = {l.toss_id for l in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id)) if l.toss_id}
    ids |= {l.toss_id for l in await s.scalars(select(PlanOrderBook).where(PlanOrderBook.plan_id == plan.id)) if l.toss_id}
    return [i for i in ids if (raw.conds.get(i) or {}).get("status") == "WATCHING"
            or (raw.limits.get(i) or {}).get("status") == "OPEN"]


# ── 새 막음 1 · Kill · 마감 · 스위치 끔 뒤 아는 번호는 취소하고 모름은 알린다 ─────────────────────

async def test_kill_cancels_known_ids_even_when_a_modify_result_is_unknown(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    kill = [(False, True)]
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    eng.kill_state = lambda: kill[0]
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.fail_modify = 1
        await eng._modify_leg(s, plan, leg, qty=leg.qty)
        assert await ob.unresolved_lines(s, plan.id)
        kill[0] = (True, False)                                              # Kill 「매도도 멈춤」
        await eng.tick_plan(s, plan)
        assert await known_open(s, plan, raw) == []                          # 아는 번호는 모두 취소
        assert plan.state == state.HALTED
        assert any(a[1] == "새 주문이 있을 수 있음" for a in eng._alerts)       # 모르는 새 주문은 ⑨ 긴급
        assert await ob.unresolved_lines(s, plan.id)                         # 모름 줄은 그대로 사람 확인 대기
        check_sells(raw)


async def test_close_does_not_close_while_unknown_lines_remain_and_cancels_known_ids(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.fail_modify = 1
        await eng._modify_leg(s, plan, leg, qty=leg.qty)
        s.add(PlanFill(plan_id=plan.id, side="SELL", qty=60, price=9, order_ref="x", fill_seq=60))
        await s.flush()
        raw.acct = 0
        await eng.tick_plan(s, plan)
        assert plan.state == state.HALTED                                    # CLOSED 로 넘기지 않는다
        assert await known_open(s, plan, raw) == []
        assert any(a[1] == "새 주문이 있을 수 있음" for a in eng._alerts)
        check_sells(raw)
        ln = (await ob.unresolved_lines(s, plan.id))[0]
        await ob.human_resolve(s, plan, ln.id, "not_created")                # 사람이 확인한 뒤에야
        await eng.tick_plan(s, plan)
        await eng._close(s, plan)
        assert plan.state == state.CLOSED


async def test_switch_off_keeps_unknown_buy_unconfirmed_and_alerts(plan_db, monkeypatch):
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
        leg = (await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.role == "buy"))).one()
        assert leg.status == "UNCERTAIN"
        assert any(a[1] == "새 주문이 있을 수 있음" for a in eng._alerts)
        assert runtime_of(plan).get("rearm_buy") in (None, False)              # 모름인 동안 다시 사지 않는다
        check_sells(raw)


# ── 새 높음 1 · 정지 중 확정한 TP1 체결은 재개 뒤에도 TP1 을 다시 내지 않는다 ───────────────────

async def test_tp1_human_fill_while_halted_is_processed_on_resume_not_reissued(plan_db, monkeypatch):
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
        assert plan.state == state.HALTED
        ln = [l for l in await ob.unresolved_lines(s, plan.id) if l.role == "tp1"][0]
        for k, c in list(raw.conds.items()):
            if c["client_id"] == ln.client_order_id:
                raw.trigger(k, fill=True)
        raw.acct = 60 - ln.qty
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=ln.qty)
        eng.clock.advance(seconds=5)
        await eng.tick_plan(s, plan)                                          # 정지 중 한 걸음
        assert runtime_of(plan).get("tp1_filled_human") is True               # 표시는 처리 전에 지우지 않는다
        await eng.resume_plan(s, plan)
        assert plan.state in (state.TP1_WAIT, state.TRAILING)                 # 재개하며 처리됨
        assert not runtime_of(plan).get("tp1_filled_human")
        await eng.tick_plan(s, plan)
        creates = [c for c in raw.calls if c[0] == "cond_create" and "tp1" in str(c[-1])]
        assert len(creates) == 1                                              # TP1 은 한 번만
        check_sells(raw)


# ── 중간 1 · 같은 이름 줄을 쌓지 않는다 · 열려 있음 확정 뒤 다시 묻지 않는다 · 빈 조회는 연속 확인 ───────

async def test_missing_line_not_stacked_and_not_asked_again_after_human_open(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = FakeRaw("9.60")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))

    async def none_get(s_, i):
        return None

    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=leg)
        oid = next(iter(raw.limits))
        raw.list_hidden_ids.add(oid)
        raw.limit_get = none_get
        await eng.sync_orders(s, plan)
        assert not await ob.unresolved_lines(s, plan.id)                     # 한 번 빈 조회로는 사람 확인으로 보내지 않는다
        await eng.sync_orders(s, plan)
        unresolved = [l for l in await ob.unresolved_lines(s, plan.id) if l.client_order_id.startswith("missing-")]
        assert len(unresolved) == 1
        await ob.human_resolve(s, plan, unresolved[0].id, "open", toss_id=oid, kind="limit")
        for _ in range(5):
            eng.clock.advance(seconds=5)
            await eng.sync_orders(s, plan)
        allm = list(await s.scalars(select(PlanOrderBook).where(PlanOrderBook.client_order_id.like("missing-%"))))
        assert len(allm) == 1 and allm[0].state == "open"                    # 새 줄이 쌓이지 않았다
        check_sells(raw)


async def test_unresolved_same_name_line_is_reused_even_if_first_line_was_resolved(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        a = await ob._new_missing_line(s, plan, leg=leg, resv=None, role="sl", side="SELL", qty=20, price=9, toss_id="C1", reason="t")
        await ob.human_resolve(s, plan, a.id, "not_created")
        b = await ob._new_missing_line(s, plan, leg=leg, resv=None, role="sl", side="SELL", qty=20, price=9, toss_id="C1", reason="t")
        c = await ob._new_missing_line(s, plan, leg=leg, resv=None, role="sl", side="SELL", qty=20, price=9, toss_id="C1", reason="t")
        assert b.id == c.id and b.id != a.id                                 # 미확정 줄은 하나만
        check_sells(raw)


# ── 중간 2 · 취소 뒤 확인 실패는 체결 0 이 아니다 · 다시 팔지 않고 묶는다 ──────────────────────────

async def test_cancel_and_reprice_with_blind_lookup_does_not_resell(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw = FakeRaw("9.60")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        await eng._sell_cross(s, plan, seq=1, qty=20, cur=D("9.60"), kind="immediate", old_leg=leg)
        r = (await s.scalars(select(PlanSellReservation).where(PlanSellReservation.plan_id == plan.id,
                                                              PlanSellReservation.active.is_(True)))).first()
        creates = raw.count("limit_create")
        orig = raw.limit_get
        calls = {"n": 0}

        async def blind_after_cancel(s_, i):
            calls["n"] += 1
            return await orig(s_, i) if calls["n"] == 1 else None             # 취소 뒤 읽기가 빈 값

        raw.limit_get = blind_after_cancel
        await eng._cancel_and_reprice(s, plan, r, D("9.60"))
        assert raw.count("limit_create") == creates                           # 다시 팔지 않았다
        assert r.active is True                                               # 예약은 묶어 둔다
        raw.list_hidden_ids.add(r.order_ref)                                   # 목록에도 안 보인다
        raw.limit_get = lambda s_, i: _none()
        await eng.sync_orders(s, plan)
        assert any(l.role == "sell" and l.state == "needs_human" for l in await ob.unresolved_lines(s, plan.id))
        check_sells(raw)


async def _none():
    return None


# ── 중간 3 · 일부 체결 확정 뒤 남은 주문이 살아 있으면 다시 맞추기가 경고한다 ──────────────────────

async def test_partial_confirm_with_live_remainder_is_flagged_by_resync(plan_db, monkeypatch):
    cfg(monkeypatch, settle=0)
    raw, eng = await setup()
    async with get_session() as s:
        plan = await unknown_leg(s, eng, raw, qty=20)                         # 토스에는 20주 조건주문이 살아 있지만 번호를 모른다
        eng.clock.advance(seconds=1)
        await ob.reconcile(s, eng, plan)
        ln = (await lines(s, plan, state="needs_human"))[0]
        await ob.human_resolve(s, plan, ln.id, "filled", filled_qty=12, remainder_cancelled=True)   # 거짓 확인(실제로는 살아 있음)
        raw.acct = 48
        await eng.ensure_ladder(s, plan)
        eng._alerts.clear()
        rep = await resync.resync_plan(s, eng, plan)
        assert rep["ok"] is False
        assert any(a[1] == "매도 합이 계좌 보유를 넘음" for a in eng._alerts)       # 다음 다시 맞추기에 경고가 나온다


async def test_partial_confirm_response_carries_the_warning_text(api):
    plan = await mk_plan(api)
    await _api_line(plan["id"], qty=6)
    cookie(api)
    lid = (await api.get(f"/api/v1/plans/{plan['id']}/unknown-orders")).json()["orders"][0]["id"]
    r = await api.post(f"/api/v1/plans/{plan['id']}/unknown-orders/{lid}/resolve",
                       json={"decision": "filled", "filled_qty": 3, "remainder_cancelled": True}, headers=OK_ORIGIN)
    assert r.status_code == 200 and "남은 주문" in r.json()["warning"]


# ── 중간 4 (의도 표시) · 옛 다리가 닫힌 수정 줄은 묶인 수량으로 센다 (설계대로) ───────────────────

async def test_by_design_modify_line_with_closed_old_leg_counts_as_bound(plan_db, monkeypatch):
    cfg(monkeypatch, settle=90)
    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw, regular=REG, clock=Clock(NOW))
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        leg = (await legs_of(s, plan))[0]
        raw.fail_modify = 1
        await eng._modify_leg(s, plan, leg, qty=leg.qty)
        raw.trigger(leg.toss_id, fill=True)                                    # 옛 다리는 체결로 닫힘
        raw.acct -= leg.qty
        await eng.sync_orders(s, plan)
        assert leg.status == "FILLED"
        exp = await ob.exposure(s, plan.id)
        assert exp["bound_new"] == 20 and exp["unknown_modify"] == 0           # 설계: 닫힌 옛 다리 + 모름 수정 줄 = 묶음
        check_sells(raw)


# ── 낮음 · 「판정 한 곳」 구조 시험 (금지 모양 · 허용 곳은 파일:함수로 명시) ──────────────────────

ALLOWED = {"engine.py:_cancel_leg_keep_unknown", "engine.py:_close"}       # UNCERTAIN 을 보고도 상태를 CANCELED/FILLED 로 쓰는 곳 (취소 처리 · 알림 동반)


def find_violations(src: str, fname: str) -> list[str]:
    out = []
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        key = f"{fname}:{fn.name}"
        consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        closes = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                  and n.value.value in ("CANCELED", "FILLED")
                  and any(isinstance(t, ast.Attribute) and t.attr == "status" for t in n.targets)]
        if "UNCERTAIN" in consts and closes and key not in ALLOWED:
            out.append(f"{key} · UNCERTAIN 을 보고 상태를 닫음")
        for n in ast.walk(fn):
            # 단건 조회가 빈 값이면 바로 예약을 풀거나 다리를 닫는 모양: if x is None: ... r.active = False / leg.status = ...
            if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and len(n.test.ops) == 1 \
                    and isinstance(n.test.ops[0], ast.Is) and isinstance(n.test.comparators[0], ast.Constant) \
                    and n.test.comparators[0].value is None:
                for m in ast.walk(n):
                    if isinstance(m, ast.Assign) and isinstance(m.value, ast.Constant) and any(
                            isinstance(t, ast.Attribute) and t.attr in ("active", "status") for t in m.targets) \
                            and m.value.value in (False, "CANCELED", "FILLED"):
                        if "get" in ast.dump(n.test.left) or isinstance(n.test.left, ast.Name) and n.test.left.id in ("g", "info", "before", "after"):
                            out.append(f"{key} · 빈 조회를 보고 바로 닫음")
            # limit_get(...) or {} : 빈 조회를 체결 0 으로 보는 모양
            if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and len(n.values) == 2 \
                    and isinstance(n.values[1], ast.Dict) and not n.values[1].keys and "limit_get" in ast.dump(n.values[0]):
                out.append(f"{key} · limit_get(...) or {{}}")
    return out


def test_unknown_order_judgment_lives_only_in_orderbook_module():
    root = pathlib.Path(__file__).resolve().parents[1] / "execution" / "plan"
    bad = []
    for f in sorted(root.glob("*.py")):
        if f.name == "orderbook.py":
            continue
        bad += find_violations(f.read_text(), f.name)                       # engine.py 포함
    assert bad == [], bad
    assert "PlanLegPending" not in (root / "models.py").read_text()


def test_structure_check_fails_when_a_forbidden_shape_is_planted():
    planted = '''
async def f(self, s, plan, r, leg):
    g = await self.gate.limit_get(s, r.order_ref)
    if g is None:
        r.active = False
async def h(self, s, plan, r, leg):
    before = await self.gate.limit_get(s, r.order_ref) or {}
async def k(self, s, plan, leg):
    if leg.status == "UNCERTAIN":
        leg.status = "CANCELED"
'''
    found = find_violations(planted, "engine.py")
    assert any("빈 조회" in x for x in found) and any("or {}" in x for x in found) and any("UNCERTAIN" in x for x in found)
