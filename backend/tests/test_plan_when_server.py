"""1116-01 서버 단계 S1~S6 시험 (가짜 토스 · 가상 종목 TESTA · TESTB · 실종목 · 금액 없음)."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from backend.execution.plan import drafts, state, us_holidays
from backend.execution.plan.engine import params_of, set_params
from backend.execution.plan.models import Plan
from backend.execution.plan.when import build_when, timestop_start
from backend.services.db import get_session
from backend.tests.plan_fakes import Clock, FakeRaw, make_engine, plan_db, seed_holding  # noqa: F401
from backend.tests.test_plan_api import J, OK_ORIGIN, PARAMS, TOKEN, api, cookie, mk_plan  # noqa: F401

D_ = date.fromisoformat

# NYSE 공식 휴장일 표 (https://www.nyse.com/markets/hours-calendars · 2026-11-25 11:40 KST 에 연 페이지에서 옮김)
OFFICIAL = {
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
           "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
           "2027-09-06", "2027-11-25", "2027-12-24"],
    2028: ["2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
           "2028-11-23", "2028-12-25"],
}
EARLY_CLOSE = ["2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"]


# ── S4 휴장일 ──────────────────────────────────────────────────

@pytest.mark.parametrize("year", [2026, 2027, 2028])
def test_rule_holidays_match_official_table(year):
    assert sorted(d.isoformat() for d in us_holidays.rule_holidays(year)) == OFFICIAL[year]


def test_early_close_days_are_trading_days_and_saturday_new_year_has_no_substitute():
    all_h = us_holidays.holidays_around(D_("2027-06-01"))
    for d in EARLY_CLOSE:
        assert D_(d) not in all_h
    assert D_("2027-12-31") not in all_h and D_("2028-01-01") not in all_h and D_("2028-01-03") not in all_h


def test_holidays_cached_per_year_and_failure_falls_back_to_weekends(monkeypatch):
    assert us_holidays.holidays_for_year(2026) is us_holidays.holidays_for_year(2026)

    def boom(y):
        raise RuntimeError("x")

    monkeypatch.setattr(us_holidays, "holidays_for_year", boom)
    assert us_holidays.holidays_around(D_("2026-11-25")) == frozenset()


def test_extra_file_adds_dates_and_verified_years(tmp_path, monkeypatch):
    f = tmp_path / "extra.json"
    f.write_text('{"dates": ["2029-01-05"], "verified_years": [2029]}', encoding="utf-8")
    monkeypatch.setattr(us_holidays, "EXTRA_FILE", f)
    us_holidays.holidays_for_year.cache_clear()
    try:
        assert D_("2029-01-05") in us_holidays.holidays_for_year(2029)
        assert us_holidays.is_verified_year(2029) and not us_holidays.is_verified_year(2030)
        f.write_text("{깨짐", encoding="utf-8")
        us_holidays.holidays_for_year.cache_clear()
        assert D_("2029-01-05") not in us_holidays.holidays_for_year(2029)            # 깨진 파일은 무시
    finally:
        monkeypatch.undo()
        us_holidays.holidays_for_year.cache_clear()


def test_draft_close_day_uses_holidays():
    cat = drafts.Catalyst(D_("2026-12-02"), "company", True, "x")
    plain = drafts.entry_window(cat).close_on
    hol = drafts.entry_window(cat, us_holidays.holidays_around(D_("2026-11-25"))).close_on
    assert plain == D_("2026-11-25") and hol == D_("2026-11-24")        # 11/26 추수감사절을 건너뛰면 하루 앞


async def test_draft_cycle_receives_holidays_and_saves_confirmed_flag(plan_db):
    eng = make_engine(FakeRaw("10"))
    data = {"catalysts": [drafts.CatalystInput("company", day=D_("2026-12-02"))], "flags": {}, "ref_price": 10.0,
            "budget_usd": 100.0, "tp1_pct": None}
    async with get_session() as s:
        await drafts.run_draft_cycle(s, eng, today=D_("2026-11-25"), symbols=["TESTA"], loader=lambda sym: data,
                                     holidays=us_holidays.holidays_around(D_("2026-11-25")))
        p = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        pr = params_of(p)
        assert pr["entry_close_at"].startswith("2026-11-24")
        assert pr["rationale"]["catalyst_confirmed"] is True and pr["rationale"]["catalyst_day"] == "2026-12-02"
        assert pr["rationale"]["window_open"] == "2026-11-02"


# ── 지킬 것 1: 이미 끌어올리기 · 정리 단계인 날은 휴장일 반영 뒤에도 끝까지 간다 ──

REG = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))
HOL = frozenset(D_(x) for x in ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"))   # 시험용: 그날은 「아직 아님」


async def test_timestop_in_lift_stage_goes_on_the_same_day_even_if_no_longer_due(plan_db):
    raw = FakeRaw("10.50")
    raw.acct = 60
    clock = Clock(datetime(2026, 11, 20, 15, 0))
    eng = make_engine(raw, regular=REG, clock=clock)
    async with get_session() as s:
        plan = await seed_holding(s, eng, extra={"announce_at": "2026-11-09T22:00:00"})
        await eng.ensure_ladder(s, plan)
        await eng._timestop_step(s, plan, clock())
        assert plan.timestop_stage == "lift"
        eng.holidays = lambda: HOL                              # 배포로 휴장일이 들어와 「아직 아님」이 됨
        clock.t = datetime(2026, 11, 20, 20, 31)
        await eng._timestop_step(s, plan, clock())
        assert plan.timestop_stage == "clean"                    # 그날 단계는 멈추지 않는다
        assert raw.count("limit_create") == 1
        # 단계에 들어가지 않은 계획은 「아직 아님」으로 돌아간다
        other = await seed_holding(s, eng, symbol="TESTB", extra={"announce_at": "2026-11-09T22:00:00"})
        await eng.ensure_ladder(s, other)
        clock.t = datetime(2026, 11, 20, 15, 0)
        await eng._timestop_step(s, other, clock())
        assert other.timestop_stage == "none"
        # 다음 날에는 lift_session 이 달라 멈춘다
        plan.timestop_lift_session = "2026-11-19"
        before = raw.count("limit_create")
        clock.t = datetime(2026, 11, 20, 20, 40)
        await eng._timestop_step(s, plan, clock())
        assert raw.count("limit_create") == before


# ── S1 · S2 · S3 승인 검사 ─────────────────────────────────────

async def _draft(s, eng, *, mode="live", params=None, source="manual", symbol="TESTA"):
    return await eng.create_draft(s, symbol=symbol, mode=mode, params=params if params is not None else dict(PARAMS), source=source)


@pytest.mark.parametrize("mode", ["paper", "live"])
@pytest.mark.parametrize("missing", ["buy_watch", "buy_order"])
async def test_approve_refuses_missing_buy_values_including_paper(plan_db, mode, missing):
    eng = make_engine(FakeRaw("10"))
    pr = {k: v for k, v in PARAMS.items() if k != missing}
    async with get_session() as s:
        plan = await _draft(s, eng, mode=mode, params=pr)
        why = await eng.approval_block_reason(s, plan)
        assert why and "매수 감시가" in why
        with pytest.raises(state.TransitionError):
            await eng.approve(s, plan, by="대표")
        set_params(plan, dict(params_of(plan), **{missing: 0}))
        assert await eng.approval_block_reason(s, plan)


async def test_approve_refuses_zero_adopt_qty_but_adopt_without_buy_values_is_allowed(plan_db):
    eng = make_engine(FakeRaw("10"))
    async with get_session() as s:
        zero = await _draft(s, eng, mode="paper", source="adopt", params={"adopt": {"qty": 0, "avg_price": 10.0}})
        assert "맡길 수량" in (await eng.approval_block_reason(s, zero))
        with pytest.raises(state.TransitionError):
            await eng.approve(s, zero, by="대표")
        ok = await _draft(s, eng, mode="paper", source="adopt", symbol="TESTB", params={"adopt": {"qty": 12, "avg_price": 10.0}})
        assert await eng.approval_block_reason(s, ok) is None
        await eng.approve(s, ok, by="대표")
        assert ok.state == state.APPROVED


async def test_block_reason_covers_state_open_plan_qty_and_caps(plan_db, monkeypatch):
    monkeypatch.setenv("PLAN_MAX_ORDER_USD", "1000")
    monkeypatch.setenv("PLAN_TOTAL_CAP_USD", "5000")
    eng = make_engine(FakeRaw("10"))
    async with get_session() as s:
        a = await _draft(s, eng)
        assert await eng.approval_block_reason(s, a) is None
        zero = await _draft(s, eng, symbol="TESTB", params=dict(PARAMS, qty=0))
        zp = dict(params_of(zero), qty=0)
        zp.pop("budget_usd", None)
        set_params(zero, zp)
        assert "수량이 0" in await eng.approval_block_reason(s, zero)
        zero.state = state.CANCELLED                      # 가상 종목 이름은 TESTA · TESTB 만 쓴다 → 끝낸 계획의 자리를 다시 쓴다
        big = await _draft(s, eng, symbol="TESTB", params=dict(PARAMS, buy_watch=500, buy_order=500, qty=60))
        assert "상한" in await eng.approval_block_reason(s, big)
        big.state = state.CANCELLED
        dup = await eng.create_draft(s, symbol="TESTB", mode="live", params=dict(PARAMS))
        a.symbol = "TESTB"
        a.state = state.APPROVED
        assert "초안만" in await eng.approval_block_reason(s, a)
        assert "열린 계획" in await eng.approval_block_reason(s, dup)


async def test_wrong_value_does_not_consume_or_send_code(api):
    plan = await mk_plan(api, "live")
    cookie(api)
    r = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"buy_order": 0}}, headers=OK_ORIGIN)
    assert r.status_code == 200
    n = len(api.phone.msgs)
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    assert c.status_code == 409 and "매수" in c.json()["detail"]
    assert len(api.phone.msgs) == n                                    # 코드를 보내지 않음
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", json={"challenge_id": 1, "code": "123456", **J}, headers=OK_ORIGIN)
    assert r.status_code == 409                                         # 코드 검사(400)까지 가지 않는다
    r = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"buy_order": 9.5}}, headers=OK_ORIGIN)
    assert r.status_code == 200
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    assert c.status_code == 200 and len(api.phone.msgs) == n + 1


# ── S5 when ───────────────────────────────────────────────────

def _plan(source="draft", state_="DRAFT", **params):
    p = Plan(mode="live", source=source, symbol="TESTA", state=state_, revision=1)
    set_params(p, params)
    p.timestop_stage = "none"
    return p


def test_timestop_from_with_thanksgiving_week_same_input_same_answer():
    hol = us_holidays.holidays_around(D_("2026-11-25"))
    a = datetime(2026, 11, 19, 21, 0)                 # 목 21:00 UTC → 평일 5개 = 11/20 · 23 · 24 · 25 · 27 (11/26 휴장)
    assert timestop_start(a, hol) == timestop_start(a, hol) == datetime(2026, 11, 30, 15, 0)       # 11/30 10:00 EST
    assert timestop_start(a, frozenset()) == datetime(2026, 11, 27, 15, 0)                         # 휴장일 없이: 하루 일찍
    w = build_when(_plan(announce_at=a.isoformat()), datetime(2026, 11, 25, 3, 0), lambda: hol)
    assert w["timestop_from"] == "2026-12-01T00:00+09:00" and w["timestop_from_date"] == "2026-12-01"
    assert w["announce_date"] == "2026-11-20" and w["d_day"] == -5


def test_timestop_from_follows_summer_time():
    hol = us_holidays.holidays_around(D_("2026-06-01"))
    start = timestop_start(datetime(2026, 6, 30, 21, 0), hol)          # 7/3 휴장 · 7/8 이 5번째 · 시작 7/9 10:00 EDT = 14:00 UTC
    assert start == datetime(2026, 7, 9, 14, 0)


def test_when_catalyst_kinds_and_stale_and_manual():
    ann = "2026-12-15T21:00:00"
    base = {"announce_at": ann, "entry_close_at": "2026-12-08T21:00:00", "entry_window_end": "2026-12-29T21:00:00"}
    now = datetime(2026, 11, 25, 3, 0)
    conf = _plan(**base, rationale={"catalyst": "촉매 날짜 = 회사 8-K · 보도자료 2026-12-15", "catalyst_confirmed": True,
                                    "catalyst_day": "2026-12-15", "window_open": "2026-11-15"})
    w = build_when(conf, now)
    assert w["catalyst_kind"] == "confirmed" and w["catalyst_confirmed"] is True and not w["basis_stale"]
    assert w["window_open_date"] == "2026-11-16" and [x["key"] for x in w["steps"]][-1] == "timestop"
    est = _plan(**base, warnings=["촉매 날짜는 추정입니다 (임상시험 등록부(추정))"],
                rationale={"catalyst": "촉매 날짜 = 임상시험 등록부(추정) 2026-12-15"})                # 옛 초안 · 글자열만
    assert build_when(est, now)["catalyst_kind"] == "estimated"
    unknown = _plan(**base, rationale={"catalyst": "알 수 없는 모양"})
    assert build_when(unknown, now)["catalyst_kind"] == "unknown" and build_when(unknown, now)["catalyst_confirmed"] is None
    edited = _plan(**dict(base, announce_at="2026-12-20T21:00:00"),
                   rationale={"catalyst": "x 2026-12-15", "catalyst_confirmed": True, "catalyst_day": "2026-12-15"})
    we = build_when(edited, now)
    assert we["basis_stale"] and we["catalyst_kind"] == "edited" and we["catalyst_confirmed"] is None
    manual = build_when(_plan(source="manual", announce_at=ann), now)
    assert manual["catalyst_kind"] == "manual" and manual["basis"] == "직접 입력" and manual["window_open"] is None


def test_when_no_announce_and_applies_texts_and_unverified_year():
    now = datetime(2026, 11, 25, 3, 0)
    w = build_when(_plan(source="manual"), now)
    assert w["announce_at"] is None and w["timestop_from"] is None and w["timestop_applies"]["applies"] is False
    assert "발표 시각이 없어" in w["timestop_applies"]["text"] and w["steps"] == []
    h = _plan(state_="HOLDING", announce_at="2026-12-15T21:00:00")
    assert build_when(h, now)["timestop_applies"]["applies"] is True
    h.timestop_stage = "stopped"
    assert "멈춤" in build_when(h, now)["timestop_applies"]["text"]
    far = build_when(_plan(announce_at="2030-03-04T21:00:00"), now)
    assert any("확인하지 못했습니다" in x for x in far["warnings"])


async def test_when_is_response_only_and_does_not_change_hash(api):
    plan = await mk_plan(api, "live")
    assert "when" in plan and "when" not in plan["params"]
    cookie(api)
    r = await api.get(f"/api/v1/plans/{plan['id']}", headers={"X-API-Token": TOKEN})
    assert r.status_code == 200 and "when" not in r.json()["approval_values"] and "when" in r.json()["plan"]
    async with get_session() as s:
        p = await s.get(Plan, plan["id"])
        assert "when" not in (p.params_json or "")
