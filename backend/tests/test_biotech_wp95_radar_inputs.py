"""WP95 · 레이더 입력 복구 · 가격 누적 (100일 · XBI) · 백필 50 상한 · 플래그 꺼짐 0회 · 13D · NLM 캐시 · v3-전체 시작일."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_h46v3_radar as radar
from backend.scripts import biotech_mcap_daily as mc
from backend.scripts import biotech_radar_inputs_weekly as wk

KST = timezone(timedelta(hours=9))
KEY = "tk-test-" + "z" * 30
TODAY = date(2026, 10, 2)


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _rt(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)


def test_history_accumulates_and_keeps_100_days(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    old = (TODAY - timedelta(days=mc.HISTORY_KEEP_DAYS + 1)).isoformat()   # P3a · 보관 400일로 변경 · 상수 기준
    mc.save_history({("AAA", old): 1.0, ("AAA", "2026-09-30"): 2.0}, TODAY)
    rows = [{"ticker": "AAA", "tngoLast": 3.0, "timestamp": "2026-10-01T20:00:00+00:00"},
            {"ticker": "XBI", "tngoLast": 90.0, "timestamp": "2026-10-01T20:00:00+00:00"}]
    res = mc.daily_prices(["AAA"], KEY, lambda *a, **k: _R(200, rows), TODAY,
                          now=lambda: datetime(2026, 10, 2, 7, 1, tzinfo=KST))
    h = mc.load_history()
    assert h == {("AAA", "2026-09-30"): 2.0, ("AAA", "2026-10-01"): 3.0, ("XBI", "2026-10-01"): 90.0}   # 보관 기간 지난 행 삭제
    assert res["history_added"] == 2


def test_backfill_capped_at_50_per_day(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    calls = []
    bars = [{**{f: 1 for f in mc.fetch_one.__globals__["TIINGO_FIELDS"]}, "date": (TODAY - timedelta(days=i)).isoformat(), "close": 10.0}
            for i in range(0, 120)]

    def get(url, params=None, headers=None):
        calls.append(url)
        return _R(200, bars)

    t0 = datetime(2026, 10, 2, 7, 0, tzinfo=KST)
    tick = {"n": 0}

    def now():
        tick["n"] += 1
        return t0 + timedelta(seconds=tick["n"])

    res = mc.backfill_prices([f"T{i}" for i in range(60)], KEY, get, TODAY, now=now)
    assert len(calls) == res["requests"] == 50 and res["remaining"] == 10
    res2 = mc.backfill_prices([f"T{i}" for i in range(50)], KEY, get, TODAY, now=now)   # 다 채운 종목만 → 완료
    assert res2["requests"] == 0 and res2["remaining"] == 0


def test_flag_off_no_requests_including_backfill(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.delenv(mc.FLAG, raising=False)
    calls = []
    res = mc.run("daily", get_tiingo=lambda *a, **k: calls.append(1))
    assert res["skipped"] is True and calls == [] and not (tmp_path / "prices").exists()


def test_xbi_always_requested(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    seen = []
    mc.daily_prices(["AAA"], KEY, lambda url, params=None, headers=None: seen.append(params) or _R(200, []), TODAY)
    assert seen[0]["tickers"].split(",")[-1] == "XBI"


def test_13d_new_filings_only_within_5_years_including_schedule_forms():
    sub = {"filings": {"recent": {
        "form": ["SC 13D", "SC 13D/A", "SCHEDULE 13G", "4", "SC 13G", "SCHEDULE 13D/A"],
        "filingDate": ["2026-09-01", "2026-09-02", "2025-01-10", "2026-09-03", "2020-01-01", "2026-09-04"],
        "accessionNumber": ["a1", "a2", "a3", "a4", "a5", "a6"]}}}
    assert [f["accession"] for f in wk.new_13dg_filings(sub, TODAY)] == ["a1", "a3"]


class _H:
    def __init__(self, code, body=None, text=""):
        self.status_code, self._b, self.text = code, body, text

    def json(self):
        return self._b


HEADER = """<PRE>SUBJECT COMPANY:
	COMPANY DATA:
		COMPANY CONFORMED NAME:			ACME BIO INC
		CENTRAL INDEX KEY:			0000000777
FILED BY:
</PRE>"""


def test_13d_registry_seed_header_and_form4(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setattr(wk, "load_registry", lambda: [{"cik": "0000000001", "institution": "Activist A"}])
    seed = tmp_path / "seed.csv"
    seed.write_text("event_id,target_cik,target_name,event_type,event_date,accession,institution,filer_cik\n"
                    "x,0000000555,Old Co,13D_new,2024-01-02,known-1,Activist A,0000000001\n")
    real_find = wk._P.find
    monkeypatch.setattr(wk._P, "find", lambda name, **k: seed if name == wk.SEED else real_find(name, **k))
    (tmp_path / "h28v2_form4_issuer_buys_x.json").write_text(json.dumps(
        {"0000000009": {"buys": [{"issuer_cik": "0000000888", "issuer_name": "Buy Co", "tx_date": "2026-09-28", "accession": "f4-1"}]}}))
    urls = []

    def get(url):
        urls.append(url)
        if "submissions" in url:
            return _H(200, {"filings": {"recent": {"form": ["SC 13D", "SCHEDULE 13D"], "filingDate": ["2024-01-02", "2026-09-29"],
                                                   "accessionNumber": ["known-1", "new-1"]}}})
        return _H(200, text=HEADER)

    res = wk.run_13d(get=get, today=TODAY)
    assert len(urls) == 2 and urls[1].endswith("new-1-index-headers.html")      # 알고 있는 신고는 다시 묻지 않음
    rows = list(__import__("csv").DictReader((tmp_path / wk.EVENTS_OUT).open()))
    assert {(r["event_type"], r["target_cik"]) for r in rows} == {("13D_new", "0000000555"), ("13D_new", "0000000777"), ("F4_buy", "0000000888")}
    assert res["added"] == 1 and res["requests"] == 2
    led = json.loads((tmp_path / "sec_usage" / "sec_usage_20261002.json").read_text())
    assert led["counts"] == {"h3_events": 2}


def test_13d_stops_on_429(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setattr(wk, "load_registry", lambda: [{"cik": "1", "institution": "A"}, {"cik": "2", "institution": "B"}])
    sent = []
    res = wk.run_13d(get=lambda url: _H(429), today=TODAY, notify=lambda t, b: sent.append(t))
    assert res["requests"] == 1 and res["blocked"] == "SEC HTTP 429" and len(sent) == 1


def test_nlm_caches_zero_and_skips_last_year(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setattr(wk, "load_candidates", lambda: [{"ticker": "A", "cik": "0000000001", "name": "Acme Bio, Inc."}])
    calls = []

    def get(url, params=None):
        calls.append(params["term"])
        return _R(200, {"esearchresult": {"count": "0"}})

    wk.run_nlm(get=get, today=TODAY, sleep=lambda s: None)
    assert len(calls) == 4                                       # pubmed·preprint × 2026·2025
    idx = json.loads((tmp_path / wk.PUBMED_OUT).read_text())
    assert idx["0000000001"]["counts"] == {"y2025": 0, "y2026": 0}   # 0 도 캐시·산출
    calls.clear()
    wk.run_nlm(get=get, today=TODAY, sleep=lambda s: None)
    assert len(calls) == 2 and all("2026/01" in t for t in calls)  # 작년 값은 다시 받지 않음


def test_nlm_stops_on_429(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setattr(wk, "load_candidates", lambda: [{"ticker": "A", "cik": "1", "name": "A"}, {"ticker": "B", "cik": "2", "name": "B"}])
    calls = []
    res = wk.run_nlm(get=lambda url, params=None: calls.append(1) or _R(429), today=TODAY, sleep=lambda s: None, notify=lambda t, b: None)
    assert res["blocked"] == "NLM HTTP 429" and len(calls) == 1


def test_v3_full_start_recorded_once(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    got = []
    assert radar.record_v3_full_start(["h3_events"], "20261005", notify=got.append) is None
    assert radar.record_v3_full_start([], "20261006", notify=got.append) == "2026-10-06"
    assert radar.record_v3_full_start([], "20261007", notify=got.append) == "2026-10-06" and got == ["2026-10-06"]


def test_h6_membership_not_a_designed_input():
    assert "h6_membership" not in radar.DESIGNED_INPUTS and "h3_prices_merged" not in radar.DESIGNED_INPUTS


def test_stale_ticker_skipped_after_backfill(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    old = [{**{f: 1 for f in mc.fetch_one.__globals__["TIINGO_FIELDS"]}, "date": (TODAY - timedelta(days=30 + i)).isoformat(), "close": 5.0}
           for i in range(60)]
    calls = []
    res = mc.backfill_prices(["STALE"], KEY, lambda *a, **k: calls.append(1) or _R(200, old), TODAY)
    assert len(calls) == 1 and res["remaining"] == 0                       # 마지막 거래일이 30일 전 → 제외
    res2 = mc.backfill_prices(["STALE"], KEY, lambda *a, **k: calls.append(1) or _R(200, old), TODAY)
    assert len(calls) == 1 and res2["requests"] == 0                       # 다음 날도 다시 받지 않음


def test_seed_file_not_picked_up_as_radar_input():
    import fnmatch
    assert not fnmatch.fnmatch(wk.SEED, "h3_events_*.csv")   # 씨앗이 주간 산출보다 먼저 레이더 입력이 되지 않게
