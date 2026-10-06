"""P3a ② submissions 일일 단계 · ③ companyfacts 재무 (12개월 영업현금흐름 · 남은 개월 수 · 증자 반영 전).

③ 수치는 P2 번들 (docs/plans/biotech/fable-bundles/20261004_PRD-P2.zip) 의 companyfacts 원본에서 인용했다.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_filings as bf
from backend.scripts import biotech_mcap_daily as mc
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger

TODAY = date(2026, 10, 5)


def _rt(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)


def _sub(rows: list[tuple], files: bool = False, tickers=("AAA",)) -> dict:
    """rows = (form, filingDate, acceptanceDateTime, accessionNumber, items)."""
    cols = {k: [] for k in bf.KEEP_FIELDS}
    for form, fd, acc, accn, items in rows:
        for k, v in zip(bf.KEEP_FIELDS, (form, fd, acc, accn, items, f"{accn}.htm")):
            cols[k].append(v)
    return {"tickers": list(tickers), "filings": {"recent": cols, "files": [{"name": "x"}] if files else []}}


ROWS = [
    ("8-K", "2026-09-29", "2026-09-29T11:05:31.000Z", "A-8K-2", "8.01,9.01"),      # IOVA P2 인용 시각
    ("8-K", "2026-08-07", "2026-08-06T20:17:59.000Z", "A-8K-1", "2.02,9.01"),
    ("424B5", "2026-08-01", "2026-08-01T21:00:00.000Z", "A-424", ""),
    ("S-3", "2024-03-01", "2024-03-01T21:00:00.000Z", "A-S3", ""),
    ("S-1", "2025-06-01", "2025-06-01T21:00:00.000Z", "A-S1", ""),                 # 12개월 밖
    ("4", "2026-09-30", "2026-09-30T22:00:00.000Z", "A-4", ""),
]

# ── ② ──────────────────────────────────────────────────────────────


def test_parse_recent_keeps_six_fields():
    rows = bf.parse_recent(_sub(ROWS))
    assert len(rows) == 6 and set(rows[0]) == set(bf.KEEP_FIELDS)
    assert rows[0]["acceptanceDateTime"] == "2026-09-29T11:05:31.000Z" and rows[0]["items"] == "8.01,9.01"


def test_derive_s3_offerings_last_8k():
    d = bf.derive(bf.parse_recent(_sub(ROWS)), TODAY, older_pages=False)
    assert d["s3"] == {"effective": True, "form": "S-3", "filingDate": "2024-03-01", "accessionNumber": "A-S3",
                       "expires": "2027-03-01"}
    assert [o["form"] for o in d["offerings_12m"]] == ["424B5"]                   # S-1 2025-06-01 은 12개월 밖
    assert d["last_8k"]["accessionNumber"] == "A-8K-2"
    assert d["last_8k"]["acceptance_et"] == "2026-09-29T07:05:31"                  # UTC−4 (서머타임)
    assert d["foreign_issuer"] is False and d["atm"] == "미확인"


def test_derive_s3_expired_and_unknown():
    old = [("S-3", "2023-10-01", "2023-10-01T21:00:00.000Z", "OLD", "")]
    assert bf.derive(bf.parse_recent(_sub(old)), TODAY, older_pages=False)["s3"] == {"effective": False}
    recent_only = [("4", "2025-01-02", "2025-01-02T21:00:00.000Z", "F4", "")]       # 목록이 3년을 덮지 못함 + 과거 페이지 있음
    s3 = bf.derive(bf.parse_recent(_sub(recent_only)), TODAY, older_pages=True)["s3"]
    assert s3["effective"] is None and "미확인" in s3["reason"]


def test_derive_foreign_issuer():
    rows = [("20-F", "2026-04-01", "2026-04-01T10:00:00.000Z", "F1", ""), ("6-K", "2026-08-01", "2026-08-01T10:00:00.000Z", "F2", "")]
    d = bf.derive(bf.parse_recent(_sub(rows)), TODAY, older_pages=False)
    assert d["foreign_issuer"] is True and d["foreign_forms"] == ["20-F", "6-K"]


def test_derive_former_foreign_now_domestic():
    # 2026-10-04 실행 · CNTB 유형: 20-F (2025-03-28) 뒤 10-K 로 바꿈 · 6-K 는 12개월 밖 → 국내 제출사
    rows = [("10-K", "2026-03-20", "2026-03-20T10:00:00.000Z", "K1", ""), ("20-F", "2025-03-28", "2025-03-28T10:00:00.000Z", "F1", ""),
            ("6-K", "2025-03-01", "2025-03-01T10:00:00.000Z", "F2", "")]
    d = bf.derive(bf.parse_recent(_sub(rows)), TODAY, older_pages=False)
    assert d["foreign_issuer"] is False and d["last_annual_form"] == "10-K" and d["foreign_last"] == "2025-03-28"


def test_to_et_winter_offset():
    assert bf.to_et("2026-01-15T21:30:00.000Z") == "2026-01-15T16:30:00"           # UTC−5


CANDS = [{"cik": "0000000001", "ticker": "AAA", "name": "A"}, {"cik": "0000879169", "ticker": "", "name": ""},
         {"cik": "0000000003", "ticker": "CCC", "name": "C"}]


def test_run_writes_files_and_ledger(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    calls = []

    def get(url):
        calls.append(url)
        return {"status": 200, "json": _sub(ROWS, tickers=("INCY",) if "879169" in url else ("AAA",))}

    led = SecDailyLedger.load("20261005")
    meta = bf.run_submissions(TODAY, get=get, ledger=led, cands=CANDS)
    assert meta["requests"] == 3 and len(calls) == 3 and led.counts == {"filings_submissions": 3}
    assert calls[0] == "https://data.sec.gov/submissions/CIK0000000001.json"
    der = json.loads((tmp_path / "filings" / "filings_derived_20261005.json").read_text())
    assert der["rows"]["0000879169"]["ticker"] == "INCY" and der["rows"]["0000879169"]["ticker_in_candidates"] == ""
    raw = json.loads((tmp_path / "filings" / "submissions_20261005.json").read_text())
    assert set(raw["companies_raw"]["0000000001"]["filings"][0]) == set(bf.KEEP_FIELDS)


@pytest.mark.parametrize("resp", ["403", "429"])
def test_run_stops_on_403_429(tmp_path, monkeypatch, resp):
    _rt(tmp_path, monkeypatch)
    calls = []

    def get(url):
        calls.append(url)
        if resp == "403":
            raise SecBlockedError("403")
        return {"status": 429, "json": None}

    meta = bf.run_submissions(TODAY, get=get, ledger=SecDailyLedger.load("20261005"), cands=CANDS)
    assert len(calls) == 1 and meta["requests"] == 1 and meta["blocked"]


def test_run_respects_daily_cap(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    led = SecDailyLedger.load("20261005")
    led.add("form4", bf.SEC_DAILY_CAP - 1)
    calls = []
    meta = bf.run_submissions(TODAY, get=lambda u: calls.append(u) or {"status": 200, "json": _sub(ROWS)}, ledger=led, cands=CANDS)
    assert len(calls) == 1 and meta["capped"] == 2 and led.total() == bf.SEC_DAILY_CAP


def test_raw_pruned_after_7_days(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    fdir = _P.out_dir("filings")
    (fdir / "submissions_20260920.json").write_text("{}")
    (fdir / "submissions_20260930.json").write_text("{}")
    bf.run_submissions(TODAY, get=lambda u: {"status": 200, "json": _sub(ROWS)}, ledger=SecDailyLedger.load("20261005"), cands=CANDS[:1])
    assert not (fdir / "submissions_20260920.json").exists() and (fdir / "submissions_20260930.json").exists()

# ── ③ ──────────────────────────────────────────────────────────────


def _p(start, end, val, form, filed, accn="x"):
    d = {"end": end, "val": val, "form": form, "filed": filed, "accn": accn}
    if start:
        d["start"] = start
    return d


def _facts(cash: list, ocf: list, extra: dict | None = None) -> dict:
    ug = {bf.CASH_TAG: {"units": {"USD": cash}}, bf.OCF_TAG: {"units": {"USD": ocf}}}
    for k, v in (extra or {}).items():
        ug[k] = {"units": {"USD": v}}
    return {"facts": {"us-gaap": ug, "dei": {}}}


# P2 원본 인용 (CIK0001650664 · CIK0001703057 · CIK0000882796)
EDIT = _facts(
    [_p(None, "2026-06-30", 181815000, "10-Q", "2026-08-05"), _p(None, "2026-03-31", 123648000, "10-Q", "2026-05-05")],
    [_p("2025-01-01", "2025-12-31", -165241000, "10-K", "2026-03-09"),
     _p("2026-01-01", "2026-06-30", -52629000, "10-Q", "2026-08-05"),
     _p("2025-01-01", "2025-06-30", -98011000, "10-Q", "2026-08-05"),
     _p("2026-01-01", "2026-03-31", -23061000, "10-Q", "2026-05-05"),
     _p("2025-01-01", "2025-06-30", -99000000, "10-Q", "2025-08-01")],                # 옛 제출값 · 늦은 제출이 이김
    {"LongTermDebtNoncurrent": [_p(None, "2026-06-30", 48238000, "10-Q", "2026-08-05")],
     "Liabilities": [_p(None, "2026-06-30", 132083000, "10-Q", "2026-08-05")]})
ABCL = _facts(
    [_p(None, "2026-06-30", 120065000, "10-Q", "2026-08-05")],
    [_p("2025-01-01", "2025-12-31", -131295000, "10-K", "2026-02-24"),
     _p("2026-01-01", "2026-06-30", -7600000, "10-Q", "2026-08-05"),
     _p("2025-01-01", "2025-06-30", -43958000, "10-Q", "2026-08-05"),
     _p("2026-01-01", "2026-03-31", -33523000, "10-Q", "2026-05-11")])
BCRX = _facts(
    [_p(None, "2026-06-30", 154972000, "10-Q", "2026-08-05")],
    [_p("2025-01-01", "2025-12-31", 347369000, "10-K", "2026-02-26"),
     _p("2026-01-01", "2026-06-30", 42551000, "10-Q", "2026-08-05"),
     _p("2025-01-01", "2025-06-30", 13785000, "10-Q", "2026-08-05")])


def test_ttm_edit():
    t = bf.extract_finance(EDIT)["ocf_ttm"]
    assert t["ttm"] == -165241000 + -52629000 - -98011000 == -119859000
    assert t["method"] == "annual+ytd-prior_ytd" and t["prior_ytd"]["filed"] == "2026-08-05"


def test_ttm_abcl_uses_ytd_not_quarter():
    t = bf.extract_finance(ABCL)["ocf_ttm"]
    assert t["ttm"] == -131295000 + -7600000 - -43958000 == -94937000
    assert t["ytd"]["start"] == "2026-01-01" and t["ytd"]["end"] == "2026-06-30"


def test_runway_edit_and_abcl():
    e = bf.runway(bf.extract_finance(EDIT), None, date(2026, 10, 2))
    assert e["months_qe"] == round(181815000 / (119859000 / 12), 2) == 18.2
    assert e["months_today"] == round(18.2029 - 94 / bf.MONTH_DAYS, 2) and e["label"] == "그 사이 증자가 없다고 가정"
    a = bf.runway(bf.extract_finance(ABCL), None, date(2026, 10, 2))
    assert a["months_qe"] == round(120065000 / (94937000 / 12), 2) == 15.18


def test_runway_bcrx_no_burn():
    b = bf.runway(bf.extract_finance(BCRX), None, TODAY)
    assert b["ocf_ttm"] == 347369000 + 42551000 - 13785000 and b["label"] == "현금 소모 없음" and b["months_qe"] is None


def test_elapsed_matches_prd_example():
    # PRD FR-5 예: 분기 말 (6/30) 기준 13.5개월은 10/2 기준 약 10.4개월
    assert round(13.5 - (date(2026, 10, 2) - date(2026, 6, 30)).days / bf.MONTH_DAYS, 1) == 10.4


def test_runway_raise_after_quarter_end():
    filings = {"foreign_issuer": False, "offerings_12m": [{"form": "424B5", "filingDate": "2026-08-12", "accessionNumber": "Z"},
                                                          {"form": "S-3", "filingDate": "2026-07-01", "accessionNumber": "Y"}]}
    r = bf.runway(bf.extract_finance(EDIT), filings, TODAY)
    assert r["label"] == "증자 반영 전" and r["months_today"] is None and r["months_qe"] == 18.2
    assert [x["accessionNumber"] for x in r["raises_after_qe"]] == ["Z"]


def test_ttm_missing_prior_is_period_mismatch():
    f = _facts([_p(None, "2026-06-30", 1, "10-Q", "2026-08-05")],
               [_p("2025-01-01", "2025-12-31", -10, "10-K", "2026-02-01"), _p("2026-01-01", "2026-06-30", -5, "10-Q", "2026-08-05")])
    r = bf.runway(bf.extract_finance(f), None, TODAY)
    assert r["months_qe"] is None and r["reason"] == "영업현금흐름 기간 불일치"


def test_ttm_non_calendar_fiscal_year():
    # 회계연도 7/1~6/30 · 최근 10-Q 9개월 누적 (7/1~3/31)
    f = _facts([_p(None, "2026-03-31", 100, "10-Q", "2026-05-01")],
               [_p("2024-07-01", "2025-06-30", -40, "10-K", "2025-09-01"),
                _p("2025-07-01", "2026-03-31", -36, "10-Q", "2026-05-01"),
                _p("2024-07-01", "2025-03-31", -30, "10-Q", "2026-05-01")])
    assert bf.extract_finance(f)["ocf_ttm"]["ttm"] == -46


def test_latest_annual_is_ttm():
    f = _facts([_p(None, "2025-12-31", 100, "10-K", "2026-03-01")], [_p("2025-01-01", "2025-12-31", -24, "10-K", "2026-03-01")])
    r = bf.runway(bf.extract_finance(f), None, date(2026, 3, 31))
    assert r["ocf_ttm"] == -24 and r["months_qe"] == 50.0


def test_debt_and_liabilities_saved():
    fin = bf.extract_finance(EDIT)
    assert fin["debt"]["LongTermDebtNoncurrent"]["val"] == 48238000 and fin["debt"]["DebtCurrent"] is None
    assert fin["liabilities"]["val"] == 132083000
    assert set(fin["ocf_latest"]) == {"start", "end", "val", "form", "filed", "accn"}


def test_foreign_no_us_gaap():
    fin = bf.extract_finance({"facts": {"ifrs-full": {}, "dei": {}}})
    r = bf.runway(fin, None, TODAY)
    assert r["label"] == "계산 불가" and "us-gaap" in r["reason"]


def test_weekly_shares_saves_finance_without_extra_requests(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setattr(mc, "load_candidates", lambda: {"EDIT": "1650664", "ABCL": "1703057"})
    calls = []
    facts = {"1650664": EDIT, "1703057": ABCL}

    def get(url):
        calls.append(url)
        return {"status": 200, "json": facts[url.split("CIK")[1][:10].lstrip("0")]}

    mc.run("weekly", get_sec=get, today=TODAY, ledger=SecDailyLedger.load("20261005"))
    assert len(calls) == 2                                                       # 종목당 1건 그대로
    fin = json.loads((tmp_path / "finance" / "companyfacts_20261005.json").read_text())
    assert fin["rows"]["EDIT"]["ocf_ttm"]["ttm"] == -119859000 and fin["rows"]["ABCL"]["cik"] == "1703057"
    shares = json.loads((tmp_path / "mcap" / "shares_20261005.json").read_text())
    assert "_finance" not in shares


def test_daily_runway_written_from_latest_finance(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    bf.save_finance({"EDIT": {"cik": "1650664", **bf.extract_finance(EDIT)}}, date(2026, 10, 5))
    cands = [{"cik": "0001650664", "ticker": "EDIT", "name": "E"}]
    rows = [("424B5", "2026-08-12", "2026-08-12T21:00:00.000Z", "Z", "")]
    bf.run_submissions(date(2026, 10, 6), get=lambda u: {"status": 200, "json": _sub(rows)},
                       ledger=SecDailyLedger.load("20261006"), cands=cands)
    rw = json.loads((tmp_path / "finance" / "runway_20261006.json").read_text())
    assert rw["finance_asof"] == "2026-10-05" and rw["rows"]["EDIT"]["label"] == "증자 반영 전"
