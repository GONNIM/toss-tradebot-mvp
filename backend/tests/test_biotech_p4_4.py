"""P4-4 · 새 8-K 본문 단계 (하루 10 · 최신 우선 · 30일 본문 미수신 · 403/429 중단) + FR-6b 확정 · 전향 표본."""
from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.scripts import biotech_fr6c as f6
from backend.scripts import biotech_readout_text as rt
from backend.scripts.biotech_filings import to_et
from backend.scripts.biotech_sec_common import SecBlockedError

POS = "<TYPE>EX-99.1\nThe Phase 3 topline results met the primary endpoint with statistically significant benefit."
NEG = "<TYPE>EX-99.1\nTopline data: the trial did not meet its primary endpoint."
TODAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def _fixed_start(monkeypatch):
    # 픽스처 날짜는 시작일 2026-10-15 기준 · 운영 START_ET 는 배포일로 바뀐다 (Fable 2026-10-21 답 3)
    monkeypatch.setattr(rt, "START_ET", "2026-10-15")


class Ledger:
    def __init__(self, start=0):
        self.counts = {"other": start}

    def add(self, cat, n=1):
        self.counts[cat] = self.counts.get(cat, 0) + n

    def total(self):
        return sum(self.counts.values())

    def save(self):
        pass


def _raw(n=1, day="2026-10-19", items="7.01,9.01", hour=11):
    """submissions 원본 · acceptanceDateTime 은 UTC (to_et 로 동부 시각)."""
    fs = [{"form": "8-K", "filingDate": day, "acceptanceDateTime": f"{day}T{hour:02d}:{i:02d}:00.000Z",
           "accessionNumber": f"0000000001-26-{i:06d}", "items": items, "primaryDocument": "x.htm"} for i in range(n)]
    fs.append({"form": "10-Q", "filingDate": day, "acceptanceDateTime": f"{day}T12:00:00.000Z",
               "accessionNumber": "0000000001-26-999999", "items": "", "primaryDocument": "q.htm"})
    return {"0000000001": {"ticker": "AAA", "name": "A", "filings": fs}}


@pytest.fixture
def rtdir(tmp_path, monkeypatch):
    monkeypatch.setattr(f6._P, "RUNTIME_DIR", tmp_path)
    return tmp_path


def test_tag_uses_wp39_rules_verbatim():
    assert rt.tag(POS, "7.01")["candidate_direction"] == "positive"
    assert rt.tag(NEG, "8.01")["candidate_direction"] == "negative"
    assert rt.tag(POS + " " + NEG, "8.01")["candidate_direction"] == "mixed"
    assert rt.tag("<TYPE>EX-99.1 We announced a partnership.", "8.01")["candidate_direction"] == rt.NO_KW
    assert rt.tag(POS, "5.02")["candidate_direction"] == rt.NO_ITEM          # WP39 항목 2.02 · 7.01 · 8.01 만
    t = rt.tag(POS, "7.01")
    assert t["has_ex99"] is True and "topline" in t["quote"].lower()
    assert "phase 3 topline" in t["keywords"]


def test_new_8ks_since_start_newest_first():
    raw = _raw(3)
    raw["0000000001"]["filings"].append({"form": "8-K", "filingDate": "2026-10-10", "acceptanceDateTime": "2026-10-10T12:00:00.000Z",
                                         "accessionNumber": "0000000001-26-000777", "items": "8.01"})
    ks = rt.new_8ks(raw, to_et)
    assert [k["accessionNumber"] for k in ks] == ["0000000001-26-000002", "0000000001-26-000001", "0000000001-26-000000"]


def test_daily_cap_10_ledger_and_defer(rtdir):
    led, urls = Ledger(), []
    get = lambda u: (urls.append(u), {"status": 200, "text": POS})[1]   # noqa: E731
    res = rt.run_daily(_raw(12), TODAY, get, led, to_et)
    assert res["sent"] == 10 and res["received"] == 10 and res["deferred"] == 2
    assert led.counts["readout_text"] == 10
    assert urls[0].endswith("/1/000000000126000011/0000000001-26-000011.txt")      # 최신 먼저
    res2 = rt.run_daily(_raw(12), TODAY + timedelta(days=1), get, Ledger(), to_et)  # 다음 날 남은 2건
    assert res2["sent"] == 2 and res2["new"] == 2
    rows = rt.load_store()
    assert len(rows) == 12 and all(r["status"] == rt.RECEIVED for r in rows.values())


def test_30_days_not_received_without_request(rtdir):
    urls = []
    res = rt.run_daily(_raw(1, day="2026-10-15"), date(2026, 11, 20), lambda u: urls.append(u), Ledger(), to_et)
    assert urls == [] and res["expired"] == 1 and res["sent"] == 0
    assert list(rt.load_store().values())[0]["status"] == rt.NOT_RECEIVED


def test_403_and_429_stop_immediately(rtdir):
    def boom(u):
        raise SecBlockedError("403 · test")
    r1 = rt.run_daily(_raw(3), TODAY, boom, Ledger(), to_et)
    assert r1["sent"] == 1 and r1["blocked"].startswith("403")
    r2 = rt.run_daily(_raw(3), TODAY, lambda u: {"status": 429, "text": None}, Ledger(), to_et)
    assert r2["sent"] == 1 and r2["blocked"] == "SEC HTTP 429"
    assert rt.load_store() == {}


def test_daily_300_cap_stops(rtdir):
    led = Ledger(start=299)
    res = rt.run_daily(_raw(3), TODAY, lambda u: {"status": 200, "text": POS}, led, to_et)
    assert res["sent"] == 1 and res["capped"] == 2 and led.total() == 300


def test_http_error_retried_next_day(rtdir):
    rt.run_daily(_raw(1), TODAY, lambda u: {"status": 500, "text": None}, Ledger(), to_et)
    assert list(rt.load_store().values())[0]["status"] == rt.ERROR
    res = rt.run_daily(_raw(1), TODAY + timedelta(days=1), lambda u: {"status": 200, "text": NEG}, Ledger(), to_et)
    assert res["received"] == 1


def test_no_get_text_sends_nothing(rtdir):
    res = rt.run_daily(_raw(2), TODAY, None, Ledger(), to_et)
    assert res["sent"] == 0 and res["new"] == 2


# ─── 확정 · 전향 표본 ───

SNAP = {"aact_snapshot_date": "2026-10-18", "matches": [
    {"ticker": "AAA", "role": "lead", "phase": "PHASE2/PHASE3", "primary_completion_date": "2026-08-01", "nct_id": "NCT1"},
    {"ticker": "AAA", "role": "lead", "phase": "PHASE1", "primary_completion_date": "2026-09-01", "nct_id": "NCT2"},
    {"ticker": "AAA", "role": "collaborator", "phase": "PHASE4", "primary_completion_date": "2026-09-01", "nct_id": "NCT3"},
    {"ticker": "AAA", "role": "lead", "phase": "NA", "primary_completion_date": "2026-09-01", "nct_id": "NCT4"},
]}
READOUT = {"cik": "0000000001", "ticker": "AAA", "accept_et": "2026-10-19T07:05:00", "items": "7.01,9.01",
           "candidate_direction": "positive", "keywords": ["phase 2 results"]}


def test_attribute_stage_rule():
    assert f6.attribute_stage("AAA", "2026-10-19", [], SNAP)["stage"] == "3상"           # 복합 → 뒤 단계 · 가장 높은 단계
    assert f6.attribute_stage("AAA", "2027-06-01", ["phase 2 results"], SNAP)["stage"] == "2상"   # 창 밖 → 문구
    assert f6.attribute_stage("BBB", "2026-10-19", [], SNAP)["stage"] == "단계 미확인"


def test_confirm_appends_prospective_once(rtdir):
    now = datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    dec = f6.confirm("A1", True, "positive", READOUT, SNAP, now)
    assert dec["stage"] == "3상"
    rows = list(csv.DictReader(f6.prospective_path().open()))
    assert len(rows) == 1
    r = rows[0]
    assert (r["direction"], r["direction_source"], r["session"], r["base_date"], r["reaction_date"]) == \
        ("positive", "사용자 확정", "pre_open", "2026-10-16", "2026-10-19")
    with pytest.raises(ValueError, match="이미"):
        f6.confirm("A1", True, "negative", READOUT, SNAP, now)
    f6.confirm("A2", False, None, READOUT, SNAP, now)                      # 임상 발표 아님 → 결정만
    assert len(list(csv.DictReader(f6.prospective_path().open()))) == 1
    assert f6.load_decisions()["A2"] == {"clinical": False, "direction": None, "decided_at": now.isoformat(timespec="seconds")}
    with pytest.raises(ValueError, match="방향"):
        f6.confirm("A3", True, "great", READOUT, SNAP, now)


def test_prospective_counted_in_cells_with_user_source(rtdir):
    f6.confirm("A1", True, "positive", READOUT, SNAP)
    hist = {("AAA", "2026-10-16"): 10.0, ("AAA", "2026-10-19"): 12.0, ("XBI", "2026-10-16"): 100.0, ("XBI", "2026-10-19"): 101.0}
    ev = [f6.to_event(r, {}) for r in f6.load_prospective(hist)]
    assert len(ev) == 1 and ev[0]["excess"] == pytest.approx(0.19) and ev[0]["source"] == "사용자 확정"
    c = {c["label"]: c for c in f6.build_cells(ev, date(2026, 10, 20))["cells"]}
    assert c["긍정"]["source"] == {"사용자 확정": 1}


# ─── API ───

os.environ.setdefault("SNIPER_API_TOKEN", "test-token-biotech-router")


def test_api_readouts_and_confirm(tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api.routes import biotech as route
    monkeypatch.setattr(route, "DATA_DIR_RUNTIME", tmp_path)
    monkeypatch.setattr(f6._P, "RUNTIME_DIR", tmp_path)
    h = {"X-API-Token": os.environ["SNIPER_API_TOKEN"]}
    client = TestClient(app)
    assert client.get("/api/v1/biotech/fr6c/readouts").status_code == 401
    assert client.post("/api/v1/biotech/fr6c/confirm", json={"accession": "x", "clinical": False}).status_code == 401
    assert client.get("/api/v1/biotech/fr6c/readouts", headers=h).json() == {"rows": []}
    today = datetime.now(timezone.utc).date().isoformat()
    (tmp_path / "fr6c").mkdir(exist_ok=True)
    (tmp_path / "fr6c" / "readout_text.json").write_text(json.dumps({"rows": {"0000000001-26-000001": {
        **READOUT, "accept_et": f"{today}T07:05:00", "status": "수신", "quote": "q", "has_ex99": True}}}))
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps(SNAP))
    rows = client.get("/api/v1/biotech/fr6c/readouts", headers=h).json()["rows"]
    assert rows[0]["decision"] is None and rows[0]["sec_url"].endswith("/1/000000000126000001/")
    assert client.post("/api/v1/biotech/fr6c/confirm", json={"accession": "nope", "clinical": False}, headers=h).status_code == 404
    r = client.post("/api/v1/biotech/fr6c/confirm", json={"accession": "0000000001-26-000001", "clinical": True,
                                                           "direction": "mixed"}, headers=h)
    assert r.status_code == 200 and r.json()["direction"] == "mixed"
    again = client.post("/api/v1/biotech/fr6c/confirm", json={"accession": "0000000001-26-000001", "clinical": False}, headers=h)
    assert again.status_code == 409
    assert client.get("/api/v1/biotech/fr6c/readouts", headers=h).json()["rows"][0]["decision"]["clinical"] is True
