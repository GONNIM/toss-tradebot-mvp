"""1116-01 · 화면용 API 시험: 상세 · 목록 · 상태 · 검증 · 다시 맞추기 · 승인+판단 기록 · 날짜 형식 (가짜 값 · 실제 호출 0)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.execution.plan import heartbeat, state
from backend.execution.plan.engine import parse_dt, params_of, set_runtime
from backend.execution.plan.models import Plan, PlanFill, PlanLeg, PlanRequest
from backend.services.db import get_session
from backend.services.models import UserJudgment
from backend.tests.plan_fakes import D, FakeRaw, make_engine, plan_db  # noqa: F401
from backend.tests.test_plan_api import OK_ORIGIN, PARAMS, TOKEN, api, cookie, hdr, mk_plan  # noqa: F401

TZ_DATE = "2026-12-10T22:00:00+09:00"


@pytest.fixture(autouse=True)
async def _clean_judgments(plan_db):
    from sqlalchemy import delete

    async with get_session() as s:
        await s.execute(delete(UserJudgment).where(UserJudgment.page_source == "plans"))
    yield
    async with get_session() as s:
        await s.execute(delete(UserJudgment).where(UserJudgment.page_source == "plans"))


async def _holding(pid, **runtime):
    async with get_session() as s:
        p = await s.get(Plan, pid)
        p.state, p.avg_price = state.HOLDING, 10.0
        s.add(PlanFill(plan_id=p.id, side="BUY", qty=60, price=10.0, order_ref=f"seed{pid}", fill_seq=60))
        if runtime:
            set_runtime(p, **runtime)


# ── 날짜 형식 ─────────────────────────────────────────────────

def test_parse_dt_accepts_kst_offset_naive_and_z():
    assert parse_dt(TZ_DATE) == datetime(2026, 12, 10, 13, 0)
    assert parse_dt("2026-12-10T13:00:00") == datetime(2026, 12, 10, 13, 0)
    assert parse_dt("2026-12-10T13:00:00Z") == datetime(2026, 12, 10, 13, 0)


async def test_date_format_create_edit_and_non_draft_announce(api):
    cookie(api)
    r = await api.post("/api/v1/plans", json={"symbol": "TESTA", "mode": "paper",
                                              "params": {**PARAMS, "announce_at": TZ_DATE, "entry_close_at": TZ_DATE}}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["plan"]["params"]["announce_at"] == TZ_DATE
    pid = r.json()["plan"]["id"]
    bad = await api.patch(f"/api/v1/plans/{pid}", json={"values": {"announce_at": "내일 오후"}}, headers=OK_ORIGIN)
    assert bad.status_code == 400 and bad.json()["detail"]["reason"] == "bad_date"
    assert (await api.post("/api/v1/plans", json={"symbol": "TESTB", "mode": "paper", "params": {"announce_at": "x"}}, headers=OK_ORIGIN)).status_code == 400
    ok = await api.patch(f"/api/v1/plans/{pid}", json={"values": {"announce_at": "2026-12-11T09:30:00+09:00"}}, headers=OK_ORIGIN)
    assert ok.status_code == 200
    await _holding(pid)                                                    # 승인된 뒤(보유 중)에도 발표 시각은 입력 가능
    ok = await api.patch(f"/api/v1/plans/{pid}", json={"values": {"announce_at": TZ_DATE}}, headers=OK_ORIGIN)
    assert ok.status_code == 200 and ok.json()["plan"]["params"]["announce_at"] == TZ_DATE
    no = await api.patch(f"/api/v1/plans/{pid}", json={"values": {"qty": 12}}, headers=OK_ORIGIN)
    assert no.status_code == 409                                           # 다른 값은 초안만
    clear = await api.patch(f"/api/v1/plans/{pid}", json={"values": {"announce_at": None}}, headers=OK_ORIGIN)
    assert clear.status_code == 200 and clear.json()["plan"]["params"]["announce_at"] is None


async def test_engine_uses_kst_offset_dates_for_time_stop_and_entry(plan_db):
    from backend.tests.plan_fakes import Clock, seed_holding
    from datetime import timezone

    reg = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))
    raw = FakeRaw("10.50")
    raw.acct = 60
    eng = make_engine(raw, regular=reg, clock=Clock(datetime(2026, 11, 20, 15, 0)))
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-09T22:00:00+09:00"})   # 시간대 포함 날짜
        await eng.ensure_ladder(s, plan)
        await eng._timestop_step(s, plan, datetime(2026, 11, 20, 15, 0))
        assert raw.count("cond_modify") == 3                                # 끌어올리기가 돌았다 (TypeError 없이)
        entry = await eng.create_draft(s, symbol="TESTB", mode="live", params={
            "buy_watch": 9.0, "buy_order": 9.0, "qty": 6, "entry_close_at": "2026-11-20T23:00:00+09:00",
            "entry_window_end": "2026-11-27T23:00:00+09:00"})
        entry.state = state.ENTRY_ARMED
        await eng.tick_plan(s, entry, datetime(2026, 11, 20, 15, 0))        # 마감 전 · 오류 없이 지나감
        assert entry.state in (state.ENTRY_ARMED, state.HOLDING, state.ENTRY_RETRY)


# ── 상세 · 목록 · 상태 ─────────────────────────────────────────

async def test_detail_exposes_actual_legs_live_values_and_plan_fields(api):
    plan = await mk_plan(api)
    pid = plan["id"]
    await _holding(pid, price=11.0, price_at="2026-11-20T01:00:00", next_swap_at="2026-11-21T04:31:00+09:00",
                   account_qty=70, account_qty_at="2026-11-20T00:55:00", tp1_mode="watch", actual_at="2026-11-20T00:55:00",
                   actual_legs=[{"toss_id": "C1", "role": "sl", "qty": 20, "watch": 9.7, "order": 9.5}])
    async with get_session() as s:
        p = await s.get(Plan, pid)
        params = params_of(p)
        params["tp1_watch"] = 12.0
        p.params_json = json.dumps(params)
        p.approved_at = datetime(2026, 11, 20, 0, 0)
    d = (await api.get(f"/api/v1/plans/{pid}", headers=hdr())).json()
    assert d["actual_legs"] == [{"toss_id": "C1", "role": "sl", "qty": 20, "watch": 9.7, "order": 9.5}]
    assert d["actual_at"] == "2026-11-20T00:55:00"
    lv = d["live"]
    assert lv["price"] == 11.0 and lv["pnl"] == {"usd": 60.0, "pct": 10.0, "estimate": True}
    assert lv["next_swap_at"] == "2026-11-21T04:31:00+09:00" and lv["tp1_gap_pct"] == 9.09
    assert (lv["plan_qty"], lv["account_qty"], lv["outside_qty"]) == (60, 70, 10) and lv["tp1_mode"] == "watch"
    assert d["plan"]["qty"] == 60 and d["plan"]["approved_at"] == "2026-11-20T00:00:00" and d["adopt"] is None


async def test_detail_without_runtime_values_is_null_not_error(api):
    plan = await mk_plan(api)
    d = (await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())).json()
    assert d["actual_legs"] is None and d["live"]["price"] is None and d["live"]["pnl"] is None
    assert d["live"]["account_qty"] is None and d["live"]["outside_qty"] is None


async def test_trailing_detail_shows_peak_and_stop(api):
    plan = await mk_plan(api)
    await _holding(plan["id"], price=14.0)
    async with get_session() as s:
        p = await s.get(Plan, plan["id"])
        p.state, p.peak_price = state.TRAILING, 15.0
        s.add(PlanLeg(plan_id=p.id, role="sl", seq=1, qty=60, watch_price=12.75, order_price=12.5, status="WATCHING", toss_id="X"))
    d = (await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())).json()
    assert d["live"]["trailing"] == {"peak": 15.0, "stop": 12.75} and d["live"]["tp1_gap_pct"] is None


async def test_adopt_pending_detail_lists_foreign_conds_and_seconds_left(api):
    plan = await mk_plan(api, "paper")
    checked = (datetime.utcnow() - timedelta(seconds=3)).isoformat()
    async with get_session() as s:
        p = await s.get(Plan, plan["id"])
        p.state, p.approved_at = state.ADOPT_PENDING, datetime.utcnow() - timedelta(minutes=12)
        set_runtime(p, adopt_foreign=[{"toss_id": "F1", "qty": 30, "watch": 9.0, "order": 8.9, "side": "SELL"}],
                    adopt_checked_at=checked)
    a = (await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())).json()["adopt"]
    assert a["foreign_conds"][0]["toss_id"] == "F1" and a["max_gap_sec"] == 10
    assert 6 <= a["seconds_left"] <= 7 and a["waiting_minutes"] == 12


async def test_list_has_cond_count_tp1_mode_and_toss_state(api):
    plan = await mk_plan(api)
    async with get_session() as s:
        p = await s.get(Plan, plan["id"])
        p.state = state.HOLDING
        for i in (1, 2):
            s.add(PlanLeg(plan_id=p.id, role="sl", seq=i, kind="cond", qty=6, watch_price=9, order_price=8.9, status="WATCHING", toss_id=f"C{i}"))
        s.add(PlanLeg(plan_id=p.id, role="tp1", seq=1, kind="cond", qty=6, watch_price=12, order_price=12, status="WATCHING", toss_id="T"))
        await heartbeat.mark_toss(s, True, datetime(2026, 11, 20, 1, 0))
    j = (await api.get("/api/v1/plans", headers=hdr())).json()
    row = j["plans"][0]
    assert row["live_cond_count"] == 3 and row["tp1_mode"] == "register"
    assert j["toss"] == {"status": "ok", "last_ok_at": "2026-11-20T01:00:00"}
    async with get_session() as s:
        await heartbeat.mark_toss(s, False)
    assert (await api.get("/api/v1/plans", headers=hdr())).json()["toss"]["status"] == "error"


async def test_status_has_paper_flag_and_toss(api, monkeypatch):
    cookie(api)
    st = (await api.get("/api/v1/plans/executor/status")).json()
    assert st["paper_test_enabled"] is False and st["toss"]["status"] == "none"
    monkeypatch.setenv("PLAN_PAPER_TEST_ENABLED", "1")
    assert (await api.get("/api/v1/plans/executor/status")).json()["paper_test_enabled"] is True
    monkeypatch.delenv("PLAN_PAPER_TEST_ENABLED")
    await api.post("/api/v1/plans/switches/paper", json={"on": True, "reason": "시험"}, headers=OK_ORIGIN)
    assert (await api.get("/api/v1/plans/executor/status")).json()["paper_test_enabled"] is True      # 모의 스위치가 켜지면 보인다


# ── 새 계획 검증 ───────────────────────────────────────────────

def _vbody(mode="live", **p):
    return {"symbol": "TESTA", "mode": mode, "params": {"buy_watch": 9.5, "buy_order": 9.5, "qty": 12, "tp1_watch": 11.4, "tp1_order": 11.4, **p}}


def _by(r):
    return {c["key"]: c for c in r.json()["checks"]}


async def test_validate_unknown_when_executor_left_nothing_and_saves_nothing(api):
    r = await api.post("/api/v1/plans/validate", json=_vbody(), headers=hdr())
    assert r.status_code == 200
    c = _by(r)
    assert c["buying_power"]["status"] == "unknown" and "확인 못 함" in c["buying_power"]["message"]
    assert c["app_conds"]["status"] == "unknown" and c["sanity"]["status"] == "unknown"
    assert c["caps"]["status"] == "ok" and c["tick"]["status"] == "ok" and c["open_plan"]["status"] == "ok"
    assert r.json()["ok"] is True and r.json()["values"] == {"order_usd": 114.0, "qty": 12}
    async with get_session() as s:
        assert (await s.scalars(select(Plan))).first() is None             # 아무것도 저장하지 않음


async def test_validate_uses_executor_values_and_flags_problems(api):
    from backend.execution.plan.models import PlanExecutorHeartbeat

    async with get_session() as s:
        await heartbeat.save_resync_snapshot(s, buying_power=100.0, app_conds={"TESTA": 2}, now=datetime(2026, 11, 20, 1, 0))
    c = _by(await api.post("/api/v1/plans/validate", json=_vbody(), headers=hdr()))
    assert c["buying_power"]["status"] == "fail" and "100.00" in c["buying_power"]["message"]       # 114 > 100
    assert c["app_conds"]["status"] == "warn" and "2건" in c["app_conds"]["message"]
    c = _by(await api.post("/api/v1/plans/validate", json=_vbody(qty=6), headers=hdr()))
    assert c["buying_power"]["status"] == "ok"
    c = _by(await api.post("/api/v1/plans/validate", json=_vbody(buy_watch=9.456, tp1_watch=9.0), headers=hdr()))
    assert c["tick"]["status"] == "fail" and "buy_watch" in c["tick"]["message"]
    assert c["sanity"]["status"] == "fail" and "TP1" in c["sanity"]["message"]                      # TP1 이 매수가 이하
    r = await api.post("/api/v1/plans/validate", json=_vbody(qty=600), headers=hdr())
    assert _by(r)["caps"]["status"] == "fail" and r.json()["ok"] is False                             # 한 주문 상한(1000) 초과
    r = await api.post("/api/v1/plans/validate", json=_vbody("paper", announce_at="어제"), headers=hdr())
    assert _by(r)["dates"]["status"] == "fail"


async def test_validate_flags_existing_open_plan_and_sanity_uses_last_price(api):
    plan = await mk_plan(api, "paper", "TESTA")
    await _holding(plan["id"], price=20.0)
    c = _by(await api.post("/api/v1/plans/validate", json=_vbody("paper", symbol="TESTA"), headers=hdr()))
    assert c["open_plan"]["status"] == "fail"
    assert c["sanity"]["status"] == "fail" and "±40%" in c["sanity"]["message"]                      # 직전가 20 대비 9.5


async def test_validate_requires_login(api):
    assert (await api.post("/api/v1/plans/validate", json=_vbody())).status_code in (401, 403)


# ── 다시 맞추기 요청 ───────────────────────────────────────────

async def test_resync_request_header_ok_draft_rejected_and_queued(api):
    plan = await mk_plan(api)
    api.cookies.clear()
    assert (await api.post(f"/api/v1/plans/{plan['id']}/resync", headers=hdr())).status_code == 409    # 초안
    await _holding(plan["id"])
    r = await api.post(f"/api/v1/plans/{plan['id']}/resync", headers=hdr())
    assert r.status_code == 200
    async with get_session() as s:
        req = (await s.scalars(select(PlanRequest).where(PlanRequest.action == "resync"))).one()
        assert req.status == "pending" and req.plan_id == plan["id"]
    cookie(api)
    assert (await api.post(f"/api/v1/plans/{plan['id']}/resync")).status_code == 403                  # 쿠키는 Origin 필요


async def test_executor_processes_resync_and_records_runtime_for_screen(plan_db):
    from backend.execution.plan.brokers import PaperRaw
    from backend.execution.plan.runner import PlanExecutor
    from backend.tests.plan_fakes import Clock, seed_holding

    reg = (datetime.utcnow() - timedelta(hours=1), datetime.utcnow() + timedelta(hours=2))

    class RawBP(FakeRaw):
        async def buying_power_usd(self, s):
            return 321.5

    raw = RawBP("10")
    raw.acct = 60
    eng = make_engine(raw, regular=reg, clock=lambda: datetime.utcnow())

    async def notify(*a):
        return None

    ex = PlanExecutor(real_engine=eng, paper_engine=eng, paper_raw=PaperRaw(lambda s: None), notify=notify)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        await eng.ensure_ladder(s, plan)
        raw.conds["APP1"] = dict(id="APP1", status="WATCHING", symbol="TESTB", side="SELL", qty=5, watch=D(1), order=D(1),
                                 client_id="app", order_id=None, filled=0, remaining=5, avg=None)
        s.add(PlanRequest(plan_id=plan.id, action="resync", requested_by="header"))
        pid = plan.id
    async with get_session() as s:
        assert await ex.process_requests(s) == 1
    async with get_session() as s:
        p = await s.get(Plan, pid)
        req = (await s.scalars(select(PlanRequest))).one()
        assert req.status == "done"
        rt = params_of(p)["_runtime"]
        assert sorted(a["role"] for a in rt["actual_legs"]) == ["sl", "sl", "sl"] and rt["account_qty"] == 60
        assert rt["actual_legs"][0]["watch"] == 9.7 and rt["actual_legs"][0]["order"] == 9.5
        await ex._record_runtime(s, p)
        rt = params_of(p)["_runtime"]
        assert rt["price"] == 10.0 and rt["next_swap_at"].endswith("+09:00")                # 다음 전환 시각(KST)
        await ex._snapshot_for_screen(s)
        from backend.execution.plan.models import PlanExecutorHeartbeat
        hb = await s.get(PlanExecutorHeartbeat, 1)
        assert hb.toss_status == "ok" and hb.toss_ok_at is not None
        assert hb.buying_power_usd == 321.5 and json.loads(hb.app_conds_json) == {"TESTB": 1}


async def test_runtime_values_do_not_change_the_approval_hash(plan_db):
    eng = make_engine(FakeRaw())
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper", params={"qty": 6, "buy_watch": 9, "buy_order": 9})
        before = (plan.content_hash, plan.revision)
        set_runtime(plan, price=11.0, actual_legs=[])
        await eng.update_draft(s, plan, {"qty": 6})
        assert (plan.content_hash, plan.revision) == before


# ── 승인 + 판단 기록 한 트랜잭션 ─────────────────────────────────

J = {"thesis": "근거 한 줄", "invalidation_price": 8.5, "target_price": 12.0}


async def test_paper_approve_saves_judgment_in_same_transaction(api):
    plan = await mk_plan(api)
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", json={"approver": "대표", "ticker": "testa", **J}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["judgment_saved"] is True and r.json()["plan"]["state"] == "APPROVED"
    async with get_session() as s:
        j = (await s.scalars(select(UserJudgment).where(UserJudgment.page_source == "plans"))).one()
        assert (j.ticker, j.thesis_md, j.invalidation_price, j.target_price, j.page_source, j.strategy) == \
            ("TESTA", "근거 한 줄", 8.5, 12.0, "plans", "event")
        assert j.entry_price == 9.5 and j.qty == 60.0


async def test_ticker_mismatch_and_missing_judgment_are_rejected_before_anything_is_saved(api):
    plan = await mk_plan(api, "live")
    url = f"/api/v1/plans/{plan['id']}/approve"
    r = await api.post(url, json={"ticker": "ZZZ", **J}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "ticker_mismatch"
    r = await api.post(url, json={}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "judgment_required"             # 실전은 판단 기록 필수
    r = await api.post(url, json={"thesis": "x", "invalidation_price": 0}, headers=OK_ORIGIN)
    assert r.status_code == 400
    async with get_session() as s:
        assert (await s.scalars(select(UserJudgment).where(UserJudgment.page_source == "plans"))).first() is None


async def test_failed_approval_leaves_no_judgment(api, monkeypatch):
    plan = await mk_plan(api, "live")
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    monkeypatch.setenv("PLAN_MAX_ORDER_USD", "10")                                                   # 승인 단계에서 상한 위반
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", headers=OK_ORIGIN,
                       json={"challenge_id": c.json()["challenge_id"], "code": api.phone.code, **J})
    assert r.status_code == 409 and "상한" in r.json()["detail"]
    async with get_session() as s:
        assert (await s.scalars(select(UserJudgment).where(UserJudgment.page_source == "plans"))).first() is None                                # 판단 기록도 남지 않음
        assert (await s.get(Plan, plan["id"])).state == state.DRAFT


async def test_live_approve_with_code_saves_both(api):
    plan = await mk_plan(api, "live")
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", headers=OK_ORIGIN,
                       json={"challenge_id": c.json()["challenge_id"], "code": api.phone.code, "ticker": "TESTA", **J})
    assert r.status_code == 200 and r.json()["plan"]["state"] == "APPROVED"
    async with get_session() as s:
        assert len(list(await s.scalars(select(UserJudgment).where(UserJudgment.page_source == "plans")))) == 1
