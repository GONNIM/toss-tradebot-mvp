"""1116-01 · 자동 초안 v4 7절 시험 (가상 종목 · 가짜 로더 · 실제 호출 0)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from backend.execution.plan import drafts as dr
from backend.execution.plan import state
from backend.execution.plan.engine import params_of
from backend.execution.plan.models import Plan, PlanEvent
from backend.services.db import get_session
from backend.tests.plan_fakes import FakeRaw, make_engine, plan_db  # noqa: F401

TODAY = date(2026, 11, 20)


def data(cat_day=date(2026, 12, 10), **kw):
    d = {"catalysts": [dr.CatalystInput("company", day=cat_day, confidence="높음")],
         "flags": {k: False for k, _ in dr.EXCLUDE_FLAGS + dr.WARN_FLAGS}, "ref_price": "9.459", "budget_usd": 1000,
         "tp1_pct": "0.2"}
    d.update(kw)
    return d


# ── 촉매 날짜 · 창 ─────────────────────────────────────────────

def test_catalyst_priority_user_over_company_over_registry():
    c = dr.resolve_catalyst([dr.CatalystInput("registry", day=date(2026, 12, 1)),
                             dr.CatalystInput("company", day=date(2026, 12, 2), confidence="중간"),
                             dr.CatalystInput("user", day=date(2026, 12, 3))])
    assert c.day == date(2026, 12, 3) and c.source == "user" and c.confirmed and "대표 입력" in c.basis
    c = dr.resolve_catalyst([dr.CatalystInput("registry", day=date(2026, 12, 1)),
                             dr.CatalystInput("company", day=date(2026, 12, 2), confidence="중간")])
    assert c.source == "company" and "신뢰도 중간" in c.basis
    c = dr.resolve_catalyst([dr.CatalystInput("registry", day=date(2026, 12, 1))])
    assert c.source == "registry" and not c.confirmed and "추정" in c.basis
    assert dr.resolve_catalyst([]) is None


@pytest.mark.parametrize("label,expect", [("Q1", (2, 15)), ("H1", (4, 1)), ("H2", (10, 1)), ("Q4", (11, 15))])
def test_range_midpoints(label, expect):
    c = dr.resolve_catalyst([dr.CatalystInput("company", range_label=label, year=2027)])
    assert (c.day.month, c.day.day) == expect and not c.confirmed and "중간점" in c.basis


def test_confirmed_day_beats_range_in_same_source():
    c = dr.resolve_catalyst([dr.CatalystInput("company", range_label="Q4", year=2026),
                             dr.CatalystInput("company", day=date(2026, 12, 5))])
    assert c.day == date(2026, 12, 5)


def test_entry_window_30_before_14_after_and_close_five_trading_days_before_confirmed():
    cat = dr.Catalyst(date(2026, 12, 10), "company", True, "x")      # 목요일
    w = dr.entry_window(cat)
    assert (w.opens, w.ends) == (date(2026, 11, 10), date(2026, 12, 24))
    assert w.close_on == date(2026, 12, 3)                             # 5거래일 전
    est = dr.entry_window(dr.Catalyst(date(2026, 12, 10), "registry", False, "x"))
    assert est.close_on == est.ends                                    # 추정은 창 끝에 마감
    assert dr.entry_window(cat, frozenset({date(2026, 12, 7)})).close_on == date(2026, 12, 2)   # 휴장일 건너뜀


def test_window_relevance_boundaries():
    w = dr.EntryWindow(date(2026, 11, 27), date(2026, 12, 20), date(2026, 12, 10))
    assert dr.window_relevant(w, date(2026, 11, 20))                   # 7일 안에 열림
    assert not dr.window_relevant(w, date(2026, 11, 19))               # 8일 뒤 열림 → 아직
    assert dr.window_relevant(w, date(2026, 12, 20)) and not dr.window_relevant(w, date(2026, 12, 21))


# ── 제외 · 경고 ────────────────────────────────────────────────

def test_exclusions_and_warning_lines():
    f = {k: False for k, _ in dr.EXCLUDE_FLAGS + dr.WARN_FLAGS}
    assert dr.judge_flags(f) == ([], [])
    ex, wn = dr.judge_flags({**f, "delisted": True, "halted": True, "going_concern": True, "offering_30d": True})
    assert ex == ["상장폐지", "거래 정지"] and wn == ["계속기업 의문", "최근 30일 증자"]
    ex, wn = dr.judge_flags({})
    assert ex == [] and len(wn) == 7 and all(w.startswith("자료 없음") for w in wn)    # 자료 없음 → 경고 줄 (추측 없음)


def test_decide_paths():
    assert dr.decide("TESTA", data(), TODAY, open_plan=True).reasons == ["같은 종목 열린 계획"]
    assert dr.decide("TESTA", data(flags={"merger_pending": True}), TODAY).action == "exclude"
    d = dr.decide("TESTA", {"catalysts": [], "flags": {}}, TODAY)
    assert d.action == "skip" and any("촉매 날짜 확인 못 함" in w for w in d.warnings)
    assert dr.decide("TESTA", data(cat_day=date(2027, 6, 1)), TODAY).action == "skip"      # 창이 아직 멀다
    assert dr.decide("TESTA", data(cat_day=date(2026, 10, 1)), TODAY).action == "skip"     # 창이 이미 닫혔다
    assert dr.decide("TESTA", data(ref_price=None), TODAY).action == "skip"
    d = dr.decide("TESTA", data(), TODAY)
    assert d.action == "create" and d.warnings == []
    p = d.params
    assert p["buy_watch"] == 9.45 and p["qty"] % 6 == 0 and p["ladder_pcts"] == [0.03, 0.05, 0.07]
    for k in ("catalyst", "window", "buy_watch", "buy_order", "qty", "ladder_pcts", "tp1_watch"):
        assert p["rationale"][k]                                       # 값마다 근거 한 줄
    est = dr.decide("TESTA", data(catalysts=[dr.CatalystInput("registry", day=date(2026, 12, 10))]), TODAY)
    assert any("추정" in w for w in est.warnings)
    nobudget = dr.decide("TESTA", data(budget_usd=None), TODAY)
    assert nobudget.params["qty"] == 0 and "예산 미정" in nobudget.params["rationale"]["qty"]


# ── 사용자 수정 표시 · 매일 다시 계산 · 만료 ───────────────────────

async def _eng():
    return make_engine(FakeRaw())


async def test_user_edit_is_marked_only_for_editable_keys_and_system_recompute_is_not(plan_db):
    eng = await _eng()
    async with get_session() as s:
        d = dr.decide("TESTA", data(), TODAY)
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params=d.params, source="draft")
        await eng.update_draft(s, plan, {"budget_usd": 500.0, "symbol": "x"})
        assert params_of(plan)["user_edited"] == ["budget_usd"]
        await eng.update_draft(s, plan, {"tp1_watch": 99.0}, by_user=False)
        assert params_of(plan)["user_edited"] == ["budget_usd"]


async def test_daily_recompute_keeps_user_values_and_new_day_changes_the_rest(plan_db):
    eng = await _eng()
    async with get_session() as s:
        decisions, expired = await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTA"], loader=lambda sym: data())
        plan = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        assert plan.source == "draft" and plan.state == state.DRAFT and decisions[0].action == "create"
        await eng.update_draft(s, plan, {"tp1_watch": 11.5, "tp1_order": 11.5})          # 대표가 TP1 을 바꿈
        rev = plan.revision
        decisions, _ = await dr.run_draft_cycle(s, eng, today=date(2026, 11, 21), symbols=["TESTA"],
                                                loader=lambda sym: data(ref_price="9.00"))
        assert decisions[0].action == "update"
        p = params_of(plan)
        assert p["tp1_watch"] == 11.5 and "tp1_watch" in p["user_edited"]            # 사용자 수정 값 유지
        assert p["buy_watch"] == 9.00 and plan.revision > rev                         # 나머지는 다시 계산
        assert p["rationale"]["catalyst"]


async def test_user_budget_edit_recomputes_qty_from_that_budget(plan_db):
    eng = await _eng()
    async with get_session() as s:
        await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTA"], loader=lambda sym: data())
        plan = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        await eng.update_draft(s, plan, {"budget_usd": 100.0})
        await dr.run_draft_cycle(s, eng, today=date(2026, 11, 21), symbols=["TESTA"], loader=lambda sym: data(ref_price="9.00"))
        assert params_of(plan)["budget_usd"] == 100.0 and params_of(plan)["qty"] == 6   # 100 ÷ (9.00×1.001) → 6 의 배수


async def test_expired_when_window_closes_and_approved_plans_are_not_recomputed(plan_db):
    eng = await _eng()
    async with get_session() as s:
        await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTA", "TESTB"], loader=lambda sym: data())
        a = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        b = (await s.scalars(select(Plan).where(Plan.symbol == "TESTB"))).one()
        a.state = state.APPROVED                                                          # 승인된 계획
        before = a.params_json
        _, expired = await dr.run_draft_cycle(s, eng, today=date(2026, 12, 30), symbols=["TESTA", "TESTB"],
                                              loader=lambda sym: data())
        assert expired == ["TESTB"] and b.state == state.CANCELLED                        # 창이 닫혀 만료
        assert a.params_json == before and a.state == state.APPROVED


async def test_exclusion_cancels_existing_draft_and_open_plan_blocks_new_one(plan_db):
    eng = await _eng()
    async with get_session() as s:
        await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTA"], loader=lambda sym: data())
        plan = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        ds, expired = await dr.run_draft_cycle(s, eng, today=date(2026, 11, 21), symbols=["TESTA"],
                                               loader=lambda sym: data(flags={"delisted": True}))
        assert ds[0].action == "exclude" and plan.state == state.CANCELLED and expired == ["TESTA"]
        held = await eng.create_draft(s, symbol="TESTB", mode="paper", params={"qty": 6})
        held.state = state.HOLDING
        ds, _ = await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTB"], loader=lambda sym: data())
        assert ds[0].reasons == ["같은 종목 열린 계획"]


async def test_skip_does_not_delete_user_edited_draft_when_data_goes_missing(plan_db):
    eng = await _eng()
    async with get_session() as s:
        await dr.run_draft_cycle(s, eng, today=TODAY, symbols=["TESTA"], loader=lambda sym: data())
        plan = (await s.scalars(select(Plan).where(Plan.symbol == "TESTA"))).one()
        await dr.run_draft_cycle(s, eng, today=date(2026, 11, 21), symbols=["TESTA"], loader=dr.no_data_loader)
        assert plan.state == state.DRAFT


def test_summary_is_one_message_without_money():
    cat = dr.Catalyst(date(2026, 12, 10), "company", True, "x")
    w = dr.entry_window(cat)
    made = dr.DraftDecision("TESTA", "create", warnings=["a"], window=w)
    ex = dr.DraftDecision("TESTB", "exclude", reasons=["상장폐지"])
    title, body = dr.build_summary([made, ex], ["TESTC"])
    assert title == "자동 초안 1건" and "TESTA" in body and "상장폐지" in body and "만료: TESTC" in body
    assert "$" not in body and "원" not in body.replace("승인은 대표가 계획 화면에서 합니다.", "")
    assert dr.build_summary([], []) is None


# ── 잡 전체 ────────────────────────────────────────────────────

async def test_job_creates_drafts_and_sends_one_biotech_summary(plan_db, monkeypatch, tmp_path):
    from backend.execution.plan import runner

    sent = []

    async def fake_notify(level, title, body, category):
        sent.append((level, title, category))

    monkeypatch.setattr(runner, "default_notify", fake_notify)
    monkeypatch.setattr(runner, "_make_draft_loader", lambda today: (lambda sym: data()))
    monkeypatch.setenv("PLAN_RADAR_DIR", str(tmp_path))
    (tmp_path / "radar_v1_3_20261120.csv").write_text("ticker,name\nTESTA,a\nTESTB,b\n", encoding="utf-8")
    now = datetime(2026, 11, 20, 7, 15, tzinfo=dr._KST).astimezone(timezone.utc).replace(tzinfo=None)
    assert await runner.job_plan_draft(now) == "drafted"
    assert sent == [("info", "자동 초안 2건", "biotech")]                                  # 바이오 범주 1건 요약
    async with get_session() as s:
        rows = list(await s.scalars(select(Plan).where(Plan.source == "draft")))
        assert sorted(p.symbol for p in rows) == ["TESTA", "TESTB"] and all(p.state == state.DRAFT for p in rows)
    assert await runner.job_plan_draft(now) == "skip"                                      # 그날은 한 번만
