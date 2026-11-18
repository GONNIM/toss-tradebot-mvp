"""1116-01 · 자동 초안 자료 연결 시험 (가짜 바이오 산출물 · 가상 종목 · 가짜 시세 · 실제 호출 0)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.execution.plan import draft_sources as ds
from backend.execution.plan import drafts as dr
from backend.execution.plan import state
from backend.execution.plan.engine import params_of
from backend.execution.plan.models import Plan
from backend.services.db import get_session
from backend.tests.plan_fakes import FakeRaw, make_engine, plan_db  # noqa: F401

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 11, 20)


def _now_kst() -> date:
    return datetime.now(KST).date()


@pytest.fixture
def bio(tmp_path, monkeypatch):
    """기존 바이오 규칙(BIOTECH_RUNTIME_DIR 쪽)의 가짜 파일 묶음. 실제 docs · backend/data 는 보지 않게 막는다."""
    from backend.api.routes import biotech as bt

    rt = tmp_path / "rt"
    (rt / "candidates").mkdir(parents=True)
    (rt / "filings").mkdir()
    monkeypatch.setattr(bt, "DATA_DIR_RUNTIME", rt)
    monkeypatch.setattr(bt, "DATA_DIR_DOCS", tmp_path / "no_docs")
    monkeypatch.setattr(bt, "DATA_DIR", tmp_path / "no_data")
    monkeypatch.delenv("PLAN_RADAR_DIR", raising=False)
    (rt / "candidates" / "radar_v1_3_20261120.csv").write_text(
        "ticker,name,cik,time_state,status,status_checked\n"
        "TESTA,a,0000000001,C,active,Y\n"
        "TESTB,b,0000000002,C,merging_fact,Y\n"
        "TESTC,c,0000000003,C,unchecked,N\n"
        "TESTD,d,0000000004,C,active,Y\n", encoding="utf-8")
    (rt / "candidates" / "radar_excluded_20261120.json").write_text(json.dumps({"rows": [
        {"ticker": "TESTX", "name": "x", "status": "excluded_delisted", "reason": "r", "status_date": "2026-11-01", "evidence": []}]}))
    (rt / "candidates" / "biotech_candidates_v3_20261120.csv").write_text(
        "ticker,state_note\nTESTA,NCT00000001 임상 D-20 (2026-12-10 · PHASE3)\nTESTB,NCT00000002 임상 D-20 (2026-12-10 · PHASE2)\n"
        "TESTD,NCT00000004 임상 D-20 (2026-12-12 · PHASE3)\n", encoding="utf-8")
    now = _now_kst().isoformat()
    (rt / "filings" / "going_concern.json").write_text(json.dumps({"meta": {"last_run_on": now}, "rows": {
        "0000000001": {"state": "present", "form": "10-Q", "filing_date": now, "reason": "", "tries": 1},
        "0000000004": {"state": "not_found", "form": "10-Q", "filing_date": now, "reason": "", "tries": 1}}}))
    (rt / "filings" / "filings_derived_20261120.json").write_text(json.dumps({"rows": {
        "0000000001": {"offerings_12m": [{"form": "424B5", "filingDate": "2026-11-10"}]},
        "0000000004": {"offerings_12m": [{"form": "S-3", "filingDate": "2026-11-15"},
                                         {"form": "424B5", "filingDate": "2026-09-01"}]}}}))
    return rt


async def _price(sym):
    return "9.459"


# ── 순수 매핑 ─────────────────────────────────────────────────

def test_listing_flag_mapping_and_unchecked_means_no_data():
    assert ds.listing_flags("active", True) == {"delisted": False, "acquired": False, "merger_pending": False, "halted": None}
    assert ds.listing_flags("excluded_delisted", True)["delisted"] is True
    assert ds.listing_flags("merge_done_hold", True)["acquired"] is True
    assert ds.listing_flags("merging_seller", True)["merger_pending"] and ds.listing_flags("merging_fact", True)["merger_pending"]
    assert set(ds.listing_flags("active", False).values()) == {None}
    assert set(ds.listing_flags("unchecked", True).values()) == {None}


def test_going_concern_and_offering_flags():
    def mk(**k):
        return SimpleNamespace(**{"state": "present", "stale": False, "updates_stopped": False, "hypothetical_only": False, **k})

    assert ds.going_concern_flag(mk()) is True and ds.going_concern_flag(mk(state="not_found")) is False
    assert ds.going_concern_flag(mk(hypothetical_only=True)) is None and ds.going_concern_flag(mk(stale=True)) is None
    assert ds.going_concern_flag(mk(updates_stopped=True)) is None and ds.going_concern_flag(mk(state="unknown")) is None
    assert ds.going_concern_flag(None) is None
    assert ds.offering_flag({"offerings_12m": [{"form": "424B5", "filingDate": "2026-11-10"}]}, TODAY) is True
    assert ds.offering_flag({"offerings_12m": [{"form": "S-3", "filingDate": "2026-11-15"}]}, TODAY) is False   # 일괄 신고는 증자 아님
    assert ds.offering_flag({"offerings_12m": [{"form": "424B5", "filingDate": "2026-10-01"}]}, TODAY) is False  # 30일 밖
    assert ds.offering_flag(None, TODAY) is None


# ── 가짜 파일 읽기 ─────────────────────────────────────────────

async def test_loader_reads_connected_sources(bio):
    L = ds.BiotechDraftLoader(TODAY, _price)
    a = await L("TESTA")
    assert a["flags"]["delisted"] is False and a["flags"]["going_concern"] is True and a["flags"]["offering_30d"] is True
    assert a["flags"]["halted"] is None and a["flags"]["below_min_price"] is None          # 연결 못 함 → 자료 없음
    assert a["catalysts"][0].source == "registry" and a["catalysts"][0].day == date(2026, 12, 10)
    assert a["ref_price"] == "9.459" and a["budget_usd"] is None
    d = await L("TESTD")
    assert d["flags"]["going_concern"] is False and d["flags"]["offering_30d"] is False
    b = await L("TESTB")
    assert b["flags"]["merger_pending"] is True and b["ref_price"] is None                 # 제외 종목은 시세를 부르지 않음
    c = await L("TESTC")
    assert c["catalysts"] == [] and c["flags"]["delisted"] is None and c["ref_price"] is None
    x = await L("TESTX")
    assert x["flags"]["delisted"] is True                                                  # 순위에서 빠진 종목은 제외 파일에서


async def test_price_is_requested_only_when_catalyst_and_not_excluded(bio):
    calls = []

    async def price(sym):
        calls.append(sym)
        return "5"

    L = ds.BiotechDraftLoader(TODAY, price)
    for s in ("TESTA", "TESTB", "TESTC", "TESTD", "TESTX"):
        await L(s)
    assert calls == ["TESTA", "TESTD"]


async def test_missing_files_mean_no_data_not_crash(tmp_path, monkeypatch):
    from backend.api.routes import biotech as bt

    monkeypatch.setattr(bt, "DATA_DIR_RUNTIME", tmp_path / "empty")
    monkeypatch.setattr(bt, "DATA_DIR_DOCS", tmp_path / "x1")
    monkeypatch.setattr(bt, "DATA_DIR", tmp_path / "x2")
    r = await ds.BiotechDraftLoader(TODAY, _price)("TESTA")
    assert r["catalysts"] == [] and all(v is None for v in r["flags"].values()) and r["ref_price"] is None


async def test_price_failure_is_logged_and_skips_not_crashes(bio):
    async def boom(sym):
        raise RuntimeError("down")

    r = await ds.BiotechDraftLoader(TODAY, boom)("TESTA")
    assert r["ref_price"] is None


# ── 기존 저장 위치 규칙으로 레이더 찾기 · 전체 흐름 ─────────────────────

def test_radar_dirs_follow_the_biotech_runtime_rule(bio):
    dirs = dr.radar_dirs()
    assert bio / "candidates" in dirs and dr.radar_ready(dirs, TODAY) is True
    assert dr.radar_symbols(dirs, TODAY) == ["TESTA", "TESTB", "TESTC", "TESTD"]
    assert dr.radar_ready(dirs, date(2026, 11, 21)) is False


async def test_cycle_with_real_loader_creates_draft_with_no_data_warnings(plan_db, bio):
    eng = make_engine(FakeRaw())
    L = ds.BiotechDraftLoader(TODAY, _price)
    async with get_session() as s:
        decisions, _ = await dr.run_draft_cycle(s, eng, today=TODAY, symbols=dr.radar_symbols(dr.radar_dirs(), TODAY), loader=L)
        by = {d.symbol: d for d in decisions}
        assert by["TESTA"].action == "create" and by["TESTD"].action == "create"
        assert by["TESTB"].action == "exclude" and by["TESTB"].reasons == ["합병 진행"]
        assert by["TESTC"].action == "skip" and any("촉매 날짜 확인 못 함" in w for w in by["TESTC"].warnings)
        plans = {p.symbol: p for p in await s.scalars(select(Plan))}
        assert set(plans) == {"TESTA", "TESTD"} and all(p.state == state.DRAFT for p in plans.values())
        w = params_of(plans["TESTA"])["warnings"]
        assert "계속기업 의문" in w and "최근 30일 증자" in w                            # 연결한 판정이 경고 줄로
        assert any("거래 정지" in x and x.startswith("자료 없음") for x in w)              # 연결 못 한 판정은 자료 없음
        assert any("촉매 날짜는 추정" in x for x in w)                                    # 등록부 날짜는 추정 표시
        assert params_of(plans["TESTA"])["qty"] == 0 and "예산 미정" in params_of(plans["TESTA"])["rationale"]["qty"]


async def test_job_end_to_end_uses_connected_loader(plan_db, bio, monkeypatch):
    from backend.execution.plan import runner

    sent = []

    async def fake_notify(level, title, body, category):
        sent.append((title, category))

    monkeypatch.setattr(runner, "default_notify", fake_notify)
    monkeypatch.setattr(runner, "_make_draft_loader", lambda today: ds.BiotechDraftLoader(today, _price))
    now = datetime(2026, 11, 20, 7, 15, tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None)
    assert await runner.job_plan_draft(now) == "drafted"
    assert sent == [("자동 초안 2건", "biotech")]
