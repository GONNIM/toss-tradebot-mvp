"""P3a-2 ③ · 424B5 표지 규칙 ATM 확인 판정 (PRD v0.6 FR-6a · 확인 판정 전용) · 백필 · 일일 새 424B5."""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_atm_cover as atm
from backend.scripts import biotech_filings as bf
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger

# P3a ⑦ 원문 인용 (docs/plans/biotech/data/proposals/atm_cover_rule_20261004.md 4절)
ANTX = ("<html><body><p>PROSPECTUS SUPPLEMENT</p><p>$80,000,000</p><p>Common Stock</p><p>We have entered into an open market "
        "sale agreement (the &ldquo;sales agreement&rdquo;) with Jefferies LLC (&ldquo;Jefferies&rdquo;), dated April 20, "
        "2026, relating to shares of our common stock having an aggregate offering price of up to $80,000,000 from time "
        "to time through Jefferies acting as sales agent or principal.</p></body></html>")
DYN = ("<p>(To Prospectus dated March 5, 2024) 18,300,000 Shares Common Stock We are offering 18,300,000 shares of our "
       "common stock. Our underwriters ... sales agent up to $5,000,000</p>")
ATRA = ("<p>This Second Supplement amends and supplements the information in our sales agreement prospectus, dated "
        "November 13, 2023 (the Sales Agreement Prospectus). $79,269,007 Common Stock</p>")
TODAY = date(2026, 10, 7)          # 수요일


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path / "rt")
    monkeypatch.setattr(_P, "DATA_DIR_DOCS", tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    return tmp_path


def test_rule_patterns_fixed_to_proposal():
    prop = (_P.PROJECT_ROOT / "docs/plans/biotech/data/proposals/atm_cover_rule_20261004.md").read_text()
    for rx in (atm.A, atm.B, atm.C):
        assert f"`{rx.pattern}`" in prop.replace("\\|", "|")
    assert atm.HEAD == 6000 and atm.QUOTE == 60


def test_judge_confirmed_with_quotes():
    j = atm.judge(ANTX)
    assert j["result"] == "확인(표지 규칙)" and j["A"] and j["B"] and not j["C"]
    assert "open market sale agreement" in j["A_quote"] and "up to $80,000,000" in j["B_quote"]
    assert len(j["B_quote"]) <= 60 + len("up to $80,000,000") + 60


def test_judge_share_count_offering_is_unknown_not_none():
    assert atm.judge(DYN)["result"] == "미확인" and atm.judge(DYN)["C"]
    j = atm.judge(ATRA)                                         # 놓침 유형 (보충 문서) · "없음" 이 아니라 "미확인"
    assert j["result"] == "미확인" and j["A"] and not j["B"]


def test_judge_only_first_6000_chars():
    assert atm.judge("x " * 3000 + ANTX)["result"] == "미확인"


def test_plain_removes_control_and_lone_surrogate():
    t = atm.plain("<p>a\x00b\x1fc\ud800d &amp; e</p>")
    assert t == "a b c d & e"
    json.dumps(t).encode("utf-8")


def test_primary_from_sgml():
    t = "<SEC-DOCUMENT>x\n<DOCUMENT>\n<TYPE>424B5\n<TEXT>\n<html>body</html>\n</TEXT>\n</DOCUMENT>"
    assert atm.primary_from_sgml(t).strip() == "<html>body</html>"


def _derived(*items):
    """items = (cik, ticker, accn, filingDate)."""
    out = {}
    for cik, tk, accn, fd in items:
        out.setdefault(cik, {"ticker": tk, "offerings_12m": []})["offerings_12m"].append(
            {"form": "424B5", "filingDate": fd, "accessionNumber": accn, "primaryDocument": f"{accn}.htm"})
    return out


def test_company_atm_latest_positive_with_accession_and_date():
    judged = {"A1": {"result": "확인(표지 규칙)", "filingDate": "2026-04-20", "A_quote": "qa", "B_quote": "qb"},
              "A2": {"result": "미확인", "filingDate": "2026-08-01"}}
    offs = _derived(("1", "X", "A1", "2026-04-20"), ("1", "X", "A2", "2026-08-01"))["1"]["offerings_12m"]
    a = atm.company_atm(offs, judged)
    assert a["status"] == "확인(표지 규칙)" and a["accessionNumber"] == "A1" and a["filingDate"] == "2026-04-20"
    assert a["A_quote"] == "qa" and a["remaining"] == "잔여 한도 미확인"
    assert atm.company_atm(offs, {})["status"] == "미확인"


def test_judge_new_only_recent_unjudged_and_ledger(rt):
    d = _derived(("0000000001", "X", "NEW", "2026-10-05"), ("0000000001", "X", "OLD", "2026-08-01"),
                 ("0000000002", "Y", "DONE", "2026-10-06"))
    atm.save_rows(atm.seed_path(), {"DONE": {"result": "미확인", "filingDate": "2026-10-06"}})
    urls = []
    led = SecDailyLedger.load("20261007")
    r = atm.judge_new(d, TODAY, lambda u: urls.append(u) or {"status": 200, "text": ANTX}, led)
    assert urls == ["https://www.sec.gov/Archives/edgar/data/1/NEW/NEW.htm"]      # 7일 밖 · 이미 판정한 것은 받지 않음
    assert r["sent"] == 1 and r["positive"] == 1 and led.counts == {"atm_cover": 1}
    assert d["0000000001"]["atm"] == "확인(표지 규칙)" and d["0000000002"]["atm"] == "미확인"
    store = json.loads(atm.store_path().read_text())["rows"]
    assert store["NEW"]["filingDate"] == "2026-10-05" and store["NEW"]["source"] == "daily"
    urls.clear()
    atm.judge_new(d, TODAY, lambda u: urls.append(u) or {"status": 200, "text": ANTX}, led)
    assert urls == []                                                             # 다음 날 다시 받지 않음


def test_judge_new_daily_max(rt):
    d = _derived(*[("0000000001", "X", f"N{i:02d}", "2026-10-06") for i in range(15)])
    led = SecDailyLedger.load("20261007")
    r = atm.judge_new(d, TODAY, lambda u: {"status": 200, "text": DYN}, led)
    assert r["new"] == 15 and r["sent"] == atm.DAILY_MAX == 10


@pytest.mark.parametrize("resp", ["403", "429"])
def test_fetch_stops_on_403_429(rt, resp):
    items = atm.items_from_derived(_derived(*[("0000000001", "X", f"N{i}", "2026-10-06") for i in range(3)]))
    calls = []

    def get(u):
        calls.append(u)
        if resp == "403":
            raise SecBlockedError("403")
        return {"status": 429, "text": None}

    r = atm.fetch_judge(items, get, SecDailyLedger.load("20261007"), 80, "t", TODAY)
    assert len(calls) == 1 and r["blocked"] and r["rows"] == {}


def test_fetch_respects_300_cap(rt):
    led = SecDailyLedger.load("20261007")
    led.add("form4", 299)
    items = atm.items_from_derived(_derived(*[("0000000001", "X", f"N{i}", "2026-10-06") for i in range(3)]))
    r = atm.fetch_judge(items, lambda u: {"status": 200, "text": DYN}, led, 80, "t", TODAY)
    assert r["sent"] == 1 and r["capped"] == 2 and led.total() == 300


@pytest.mark.parametrize("day", [date(2026, 10, 5), date(2026, 10, 6)])
def test_backfill_refused_on_monday_tuesday(rt, day):
    with pytest.raises(SystemExit):
        atm.backfill(_derived(("1", "X", "A", "2026-09-01")), day, lambda u: {"status": 200, "text": ANTX},
                     SecDailyLedger.load("x"), set())


def test_backfill_skips_judged_and_already_and_old_and_writes_seed(rt):
    d = _derived(("0000000001", "X", "SEEN", "2026-05-01"), ("0000000001", "X", "P3A", "2026-05-02"),
                 ("0000000001", "X", "TODO", "2026-05-03"), ("0000000001", "X", "OLD", "2025-10-01"))
    atm.save_rows(atm.seed_path(), {"SEEN": {"result": "미확인", "filingDate": "2026-05-01"}})
    urls = []
    led = SecDailyLedger.load("20261007")
    r = atm.backfill(d, TODAY, lambda u: urls.append(u) or {"status": 200, "text": ANTX}, led, {"P3A"})
    assert r["todo"] == 1 and urls == ["https://www.sec.gov/Archives/edgar/data/1/TODO/TODO.htm"]
    seed = json.loads(atm.seed_path().read_text())["rows"]
    assert set(seed) == {"SEEN", "TODO"} and seed["TODO"]["source"] == "backfill_20261007"
    assert led.counts == {"atm_cover": 1}


def test_backfill_refuses_over_80(rt):
    d = _derived(*[("0000000001", "X", f"N{i:03d}", "2026-09-01") for i in range(81)])
    with pytest.raises(SystemExit):
        atm.backfill(d, TODAY, lambda u: {"status": 200, "text": DYN}, SecDailyLedger.load("20261007"), set())


def test_submissions_step_judges_new_424b5(rt):
    rows = [("424B5", "2026-10-06", "2026-10-06T21:00:00.000Z", "0000000001-26-000001", "")]
    cols = {k: [] for k in bf.KEEP_FIELDS}
    for form, fd, acc, accn, items in rows:
        for k, v in zip(bf.KEEP_FIELDS, (form, fd, acc, accn, items, "d.htm")):
            cols[k].append(v)
    sub = {"tickers": ["AAA"], "filings": {"recent": cols, "files": []}}
    texts = []
    meta = bf.run_submissions(TODAY, get=lambda u: {"status": 200, "json": sub}, ledger=SecDailyLedger.load("20261007"),
                              cands=[{"cik": "0000000001", "ticker": "AAA", "name": "A"}],
                              get_text=lambda u: texts.append(u) or {"status": 200, "text": ANTX})
    assert texts == ["https://www.sec.gov/Archives/edgar/data/1/000000000126000001/d.htm"]
    der = json.loads((_P.RUNTIME_DIR / "filings" / "filings_derived_20261007.json").read_text())["rows"]["0000000001"]
    assert der["atm"] == "확인(표지 규칙)" and der["atm_basis"]["accessionNumber"] == "0000000001-26-000001"
    assert meta["atm_cover"]["sent"] == 1


def test_submissions_blocked_sends_no_cover(rt):
    calls = []
    bf.run_submissions(TODAY, get=lambda u: {"status": 429, "json": None}, ledger=SecDailyLedger.load("20261007"),
                       cands=[{"cik": "0000000001", "ticker": "AAA", "name": "A"}],
                       get_text=lambda u: calls.append(u) or {"status": 200, "text": ANTX})
    assert calls == []
