"""1125-02 · 계획 상세 · 목록 「오른 까닭」(why) 시험 — 가짜 바이오 산출물 · 가상 종목 · 실제 호출 0.

지킬 것: 표시 전용 (상세 GET 앞뒤 revision · content_hash · params 같음) · 자료가 없거나 깨지면 200 + why null · 비로그인 401 ·
방향은 「후보 방향 · 자동 낱말 표시 · 확정 전」 · 레이더에 없는 종목 · 목록은 파일을 한 번만 읽음 · 명령문 · 신호 낱말 없음.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.execution.plan import why
from backend.tests.plan_fakes import plan_db  # noqa: F401
from backend.tests.test_plan_api import api, cookie, hdr, mk_plan  # noqa: F401

KST = timezone(timedelta(hours=9))
BANNED = ("골든", "데드", "크로스", "교차", "정배열", "역배열")


@pytest.fixture
def bio(tmp_path, monkeypatch):
    from backend.api.routes import biotech as bt

    rt = tmp_path / "rt"
    (rt / "candidates").mkdir(parents=True)
    (rt / "filings").mkdir()
    (rt / "fr6c").mkdir()
    monkeypatch.setattr(bt, "DATA_DIR_RUNTIME", rt)
    monkeypatch.setattr(bt, "DATA_DIR_DOCS", tmp_path / "no_docs")
    monkeypatch.setattr(bt, "DATA_DIR", tmp_path / "no_data")
    bt._FILE_CACHE.clear()
    (rt / "candidates" / "radar_v1_3_20261125.csv").write_text(
        "ticker,name,cik,mcap,time_state,score,expert,crowd,near,unnoticed,risk,why_easy,status,status_checked\n"
        "TESTB,b,0000000002,50M-300M,A,0.800,0.9,0.5,0.9,0.6,0.0,뉴스 예정,active,Y\n"
        "TESTA,a,0000000001,50M-300M,A,0.420,0.56,0.0,0.7,0.51,0.2,뉴스 예정,active,Y\n", encoding="utf-8")
    (rt / "candidates" / "biotech_candidates_v3_20261125.csv").write_text(
        "ticker,state_note\nTESTA,NCT00000001 임상 D-36 (2026-12-31 · PHASE1)\n", encoding="utf-8")
    now = datetime.now(KST).date().isoformat()
    (rt / "filings" / "going_concern.json").write_text(json.dumps({"meta": {"last_run_on": now}, "rows": {
        "0000000001": {"state": "not_found", "form": "10-Q", "filing_date": now, "reason": "", "tries": 1}}}))
    (rt / "filings" / "filings_derived_20261125.json").write_text(json.dumps({"rows": {
        "0000000001": {"offerings_12m": [], "s3": {"effective": True, "expires": "2028-08-29"}, "atm": "미확인",
                       "last_8k": {"acceptance_et": "2026-11-12T09:00:00", "filingDate": "2026-11-12",
                                   "accessionNumber": "0000000001-26-000001", "items": "2.02,9.01"}}}}))
    (rt / "fr6c" / "readout_text.json").write_text(json.dumps({"rows": {"0000000001-26-000001": {
        "ticker": "TESTA", "cik": "0000000001", "accept_et": "2026-11-12T09:00:00", "items": "2.02,9.01",
        "candidate_direction": "positive", "keywords": ["primary endpoint"], "quote": "met its primary endpoint"}}}))
    return rt


async def _detail(api, pid):
    r = await api.get(f"/api/v1/plans/{pid}", headers=hdr())
    assert r.status_code == 200, r.text
    return r.json()


async def test_detail_has_why_and_display_values_do_not_change(api, bio):
    plan = await mk_plan(api, symbol="TESTA")
    a = await _detail(api, plan["id"])
    b = await _detail(api, plan["id"])
    for k in ("revision",):
        assert a["plan"][k] == b["plan"][k]
    assert a["content_hash"] == b["content_hash"]
    assert a["plan"]["params"] == b["plan"]["params"] == plan["params"]
    assert "why" not in a["plan"]["params"] and "why" not in a["approval_values"]
    w = a["why"]
    assert w["asof"] == "2026-11-25" and w["in_radar"] is True
    assert w["radar"]["rank"] == 2 and w["radar"]["total"] == 2 and w["radar"]["score"] == 0.42
    assert [f["key"] for f in w["radar"]["factors"]] == ["expert", "crowd", "near", "unnoticed", "risk"]
    assert w["trial"]["pcd"] == "2026-12-31" and w["trial"]["phase_ko"] == "1상"
    assert "결과 발표일 아님" in w["trial"]["note"]


async def test_direction_is_labeled_auto_candidate_and_decision_is_separate(api, bio):
    plan = await mk_plan(api, symbol="TESTA")
    w = (await _detail(api, plan["id"]))["why"]
    k = w["eight_k"]
    assert k["direction"] == "positive" and k["direction_ko"] == "긍정" and k["decision"] is None
    assert k["items_text"] == "분기 실적" and k["url"].startswith("https://www.sec.gov/Archives/edgar/data/1/")
    # 대표 확정이 있으면 따로 나온다
    (bio / "fr6c" / "decisions.json").write_text(json.dumps({"rows": {"0000000001-26-000001": {"clinical": True, "direction": "mixed"}}}))
    w2 = (await _detail(api, plan["id"]))["why"]
    assert w2["eight_k"]["direction_ko"] == "긍정" and w2["eight_k"]["decision"]["direction_ko"] == "혼재"


async def test_risks_rows_and_no_data_rows(api, bio):
    plan = await mk_plan(api, symbol="TESTA")
    risks = {r["key"]: r for r in (await _detail(api, plan["id"]))["why"]["risks"]}
    assert risks["going_concern"]["value"] == "없음" and risks["offering_30d"]["value"] == "없음"
    assert risks["s3"]["value"] == "유효" and "2028-08-29" in risks["s3"]["note"]
    assert risks["atm"]["value"] == "확인 못 함" and risks["listing"]["value"] == "정상"
    assert risks["halt"]["value"] == "자료 없음"


async def test_ticker_not_in_radar(api, bio):
    plan = await mk_plan(api, symbol="TESTB")
    from backend.api.routes import biotech as bt

    (bio / "candidates" / "radar_v1_3_20261125.csv").write_text(
        "ticker,name,cik,mcap,time_state,score,expert,crowd,near,unnoticed,risk,why_easy,status,status_checked\n"
        "TESTA,a,0000000001,50M-300M,A,0.420,0.56,0.0,0.7,0.51,0.2,x,active,Y\n", encoding="utf-8")
    bt._FILE_CACHE.clear()
    w = (await _detail(api, plan["id"]))["why"]
    assert w["in_radar"] is False and w["radar"] is None and w["eight_k"] is None and w["trial"] is None
    assert {r["key"]: r["value"] for r in w["risks"]}["going_concern"] == "확인 못 함"


async def test_missing_or_broken_files_give_200_with_why_null(api, tmp_path, monkeypatch, bio):
    plan = await mk_plan(api, symbol="TESTA")
    for p in (bio / "candidates").glob("radar_v1_3_*.csv"):
        p.write_bytes(b"\xff\xfe\x00broken\x00")      # 깨진 레이더
    from backend.api.routes import biotech as bt

    bt._FILE_CACHE.clear()
    d = await _detail(api, plan["id"])
    assert d["why"] is None and d["plan"]["id"] == plan["id"]
    for p in (bio / "candidates").glob("radar_v1_3_*.csv"):
        p.unlink()                                     # 없음
    bt._FILE_CACHE.clear()
    assert (await _detail(api, plan["id"]))["why"] is None
    lst = (await api.get("/api/v1/plans", headers=hdr())).json()["plans"]
    assert lst[0]["why"] is None


async def test_list_has_minimal_why_without_direction(api, bio):
    await mk_plan(api, symbol="TESTA")
    row = (await api.get("/api/v1/plans", headers=hdr())).json()["plans"][0]
    assert row["why"] == {"rank": 2, "total": 2, "asof": "2026-11-25", "pcd": "2026-12-31"}


async def test_list_reads_files_once(api, bio, monkeypatch):
    await mk_plan(api, symbol="TESTA")
    await mk_plan(api, symbol="TESTB")
    calls = {"n": 0}
    real = why.load_sources

    def counted():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(why, "load_sources", counted)
    r = await api.get("/api/v1/plans", headers=hdr())
    assert r.status_code == 200 and len(r.json()["plans"]) >= 2 and calls["n"] == 1


async def test_logged_out_is_401(api, bio):
    plan = await mk_plan(api, symbol="TESTA")
    api.cookies.clear()
    assert (await api.get(f"/api/v1/plans/{plan['id']}")).status_code == 401
    assert (await api.get("/api/v1/plans")).status_code == 401


def test_no_banned_words_or_imperatives_in_server_text():
    import re
    from pathlib import Path

    src = Path(why.__file__).read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')))
    for w in BANNED:
        # 설명 문자열(독스트링)에는 낱말 자체가 있을 수 있어 표시 문자열 상수 부분만 본다
        assert w not in body.split("ITEM_KO")[1], w
    assert not re.search(r"하십시오", body)


def test_screen_source_wording_and_design():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend"
    src = (root / "components/plans/WhyCards.tsx").read_text(encoding="utf-8")
    for w in BANNED:
        assert w not in src, w
    for must in ("후보 방향: ", "자동 낱말 표시 · 확정 전", "최근 8-K (임상 발표인지 확인 전)",
                 "1차 완료 예정일 · 결과 발표일 아님 · 등록부 · 추정", "검증 중 · 추정 · 보장 아님",
                 "자료 없음 · 오늘 후보 목록에 없음", "오늘 레이더에 없음"):
        assert must in src, must
    assert "underline" not in src and "shadow" not in src and "하십시오" not in src
    lst = (root / "app/plans/page.tsx").read_text(encoding="utf-8")
    assert "whyBriefLine" in lst and "direction" not in lst.split("whyBriefLine")[1][:200]
    # 가로선은 선택 속성 · 기본값 없음 (계좌 · VIP 화면 그대로)
    ma = (root / "components/account/MaChart.tsx").read_text(encoding="utf-8")
    assert "hLines?: HLine[]" in ma and "hLines =" not in ma


def test_followup_wording_rule_created_day_asof_note_and_8k_title():
    """1125-02 후속 · 권고 ①~④ — 화면 낱말 시험 (표시 전용)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend"
    src = (root / "components/plans/WhyCards.tsx").read_text(encoding="utf-8")
    # ① 규칙 문장
    assert "초안을 만든 날 기준" in src and "같은 종목의 열린 계획이 없습니다" in src
    # 빼는 조건은 drafts.EXCLUDE_FLAGS 와 같다 · 경고 줄(계속기업 의문 · 30일 증자)은 빼는 조건으로 적지 않는다
    from execution.plan.drafts import EXCLUDE_FLAGS
    assert "빼는 조건(" + " · ".join(label for _, label in EXCLUDE_FLAGS) + ")" in src
    assert "계속기업 의문 · 최근 30일 증자는 빼는 조건이 아니며" in src
    # ② 초안 만든 날 (한국 시각 MM/DD)
    assert "createdMd(plan.created_at)" in src and "Asia/Seoul" in src and "초안 만든 날" in src
    # ③ 레이더 줄이 없을 때도 승인된 계획이면 같은 문구
    assert src.count("ASOF_NOTE") >= 3 and "why-asof-note" in src and "승인한 날의 값과 다를 수 있습니다" in src
    # ④ 대표 확정이 없으면 옛 소제목 그대로 · 있으면 바꿈
    assert "최근 8-K (임상 발표인지 확인 전)" in src and "eightKTitle(k?.decision)" in src and "대표가 임상 발표로 확정" in src
    for w in BANNED:
        assert w not in src, w
    assert "하십시오" not in src and "shadow" not in src
    lst = (root / "app/plans/page.tsx").read_text(encoding="utf-8")
    assert "break-keep" in lst and "카드 맨 위는 종목 이름표" in lst


async def test_detail_exposes_created_at_for_created_day(api, bio):
    plan = await mk_plan(api, symbol="TESTA")
    d = await _detail(api, plan["id"])
    assert d["plan"]["created_at"] and d["why"]["in_radar"] is True
