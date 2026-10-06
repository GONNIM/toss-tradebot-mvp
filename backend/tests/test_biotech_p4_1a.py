"""P4-1a (PRD 20절 · Fable 2026-10-06 18:30) · FR-6c 봉인 표본 가격 공백 종목 1회 백필 (Tiingo 일봉 · WP75-backfill 경로)."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from backend.scripts import biotech_h6_collect_prices as h6p
from backend.scripts import biotech_mcap_daily as mc

TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 7, 1, tzinfo=timezone(timedelta(hours=9)))
EXCL4 = {"BBIO", "COGT", "GPCR", "KOD"}


class _R:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


def _bar(d, c):
    return {"date": f"{d}T00:00:00.000Z", "close": c, "open": c, "high": c, "low": c, "volume": 1, "adjOpen": c, "adjHigh": c,
            "adjLow": c, "adjClose": c, "adjVolume": 1, "divCash": 0.0, "splitFactor": 1.0}


def test_sealed_sample_hash_and_real_targets_are_five():
    """봉인 표본 (ecc855dc…) 그대로 · 후보 아님 4종목 + backfill_skip APGE = 5종목 (FBRX 는 7/8 가격 있음)."""
    rows = mc.fr6c_sample_rows()
    assert rows is not None and len(rows) == 68
    assert hashlib.sha256(mc.FR6C_SAMPLE.read_bytes()).hexdigest() == mc.FR6C_SAMPLE_SHA256
    tickers = {r["ticker"] for r in rows}
    cands = sorted(tickers - EXCL4)
    fbrx = next(r for r in rows if r["ticker"] == "FBRX")
    hist = {("FBRX", fbrx["base_date"]): 1.0, ("FBRX", fbrx["reaction_date"]): 1.0}
    skip = {"APGE": "2026-10-02", "FBRX": "2026-10-02"}
    assert mc.fr6c_once_targets(rows, hist, cands, skip, {}) == ["APGE", "BBIO", "COGT", "GPCR", "KOD"]


def test_targets_rules():
    rows = [{"ticker": t, "base_date": "2025-11-03", "reaction_date": "2025-11-04"} for t in ("AIN", "BOUT", "CSKP", "DOK", "EDONE")]
    hist = {("DOK", "2025-11-03"): 1.0, ("DOK", "2025-11-04"): 1.0}
    got = mc.fr6c_once_targets(rows, hist, ["AIN", "CSKP", "DOK", "EDONE"], {"CSKP": "2026-10-02"}, {"EDONE": {"result": "filled"}})
    assert got == ["BOUT", "CSKP"]          # 후보 아님 · backfill_skip · (후보이면서 공백 = 정규 백필 · 가격 있음 · 이미 시도 = 제외)


def _env(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(h6p, "SEED_DIR", None)
    p = tmp_path / "sample.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["accession", "ticker", "base_date", "reaction_date"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(mc, "FR6C_SAMPLE", p)
    monkeypatch.setattr(mc, "FR6C_SAMPLE_SHA256", hashlib.sha256(p.read_bytes()).hexdigest())


ROWS = [{"accession": "a1", "ticker": "BBIO", "base_date": "2025-10-27", "reaction_date": "2025-10-28"},
        {"accession": "a2", "ticker": "APGE", "base_date": "2026-05-26", "reaction_date": "2026-05-27"},
        {"accession": "a3", "ticker": "ALT", "base_date": "2026-07-01", "reaction_date": "2026-07-02"}]


def test_once_fills_records_and_never_repeats(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, ROWS)
    (tmp_path / "prices").mkdir(exist_ok=True)
    (tmp_path / "prices" / "backfill_skip.json").write_text(json.dumps({"APGE": "2026-10-02"}))
    urls = []

    def get(url, params=None, headers=None):
        urls.append((url, params))
        if "bbio" in url.lower():
            return _R(200, [_bar("2025-10-27", 40.0), _bar("2025-10-28", 41.0)])
        return _R(404)                                     # APGE · 빈 응답 → 가격 없음

    res = mc.fr6c_backfill_once(["ALT"], "k" * 20, get, TODAY, now=lambda: NOW)
    assert res["requests"] == 2 and res["targets"] == ["APGE", "BBIO"]
    assert res["results"]["BBIO"]["result"] == "filled" and res["results"]["APGE"]["result"] == "empty"
    assert all(p["startDate"] == (TODAY - timedelta(days=380)).isoformat() for _, p in urls)
    hist = mc.load_history()
    assert hist[("BBIO", "2025-10-27")] == 40.0 and hist[("BBIO", "2025-10-28")] == 41.0
    usage = h6p.load_usage("202610")
    assert usage["hourly"]["2026-10-07T07"] == {"WP75-backfill-fr6c": 2}
    once = json.loads((tmp_path / "prices" / "fr6c_backfill_once.json").read_text())
    assert set(once) == {"APGE", "BBIO"}
    again = mc.fr6c_backfill_once(["ALT"], "k" * 20, get, TODAY + timedelta(days=1), now=lambda: NOW + timedelta(days=1))
    assert again["requests"] == 0 and len(urls) == 2          # 1회뿐


def test_hash_mismatch_sends_nothing(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, ROWS)
    monkeypatch.setattr(mc, "FR6C_SAMPLE_SHA256", "0" * 64)
    res = mc.fr6c_backfill_once(["ALT"], "k" * 20, lambda *a, **k: (_ for _ in ()).throw(AssertionError("요청")), TODAY,
                                now=lambda: NOW)
    assert res == {"requests": 0, "targets": [], "skipped": "sample"}


def test_429_stops_and_is_retried_next_day(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, ROWS)
    calls = []
    res = mc.fr6c_backfill_once(["ALT"], "k" * 20, lambda u, params=None, headers=None: calls.append(u) or _R(429), TODAY,
                                now=lambda: NOW)
    assert res["blocked"] == "Tiingo HTTP 429" and len(calls) == 1
    assert json.loads((tmp_path / "prices" / "fr6c_backfill_once.json").read_text()) == {}   # 기록 안 함 → 다음 날 다시


def test_hourly_limit_respected(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, ROWS)
    monkeypatch.setattr(mc, "hourly_check", lambda u, n: (False, NOW + timedelta(minutes=30)))
    res = mc.fr6c_backfill_once(["ALT"], "k" * 20, lambda *a, **k: (_ for _ in ()).throw(AssertionError("요청")), TODAY,
                                now=lambda: NOW)
    assert res["requests"] == 0 and res["blocked"].startswith("hourly_limit")


def test_daily_run_calls_once_after_backfill_unless_blocked(tmp_path, monkeypatch):
    """일일 시총 단계 · 정규 백필 뒤에 1회 백필 · 정규 백필이 막힌 날 (429 · 시간당) 은 건너뜀."""
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(h6p, "SEED_DIR", None)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setenv("TIINGO_API_KEY", "k" * 20)
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "biotech_candidates_20261007.csv").write_text("ticker,cik\nALT,1\n")
    (tmp_path / "mcap").mkdir(exist_ok=True)
    (tmp_path / "mcap" / "shares_20261005.json").write_text(json.dumps({"shares": {}}))
    monkeypatch.setattr(mc, "daily_prices", lambda *a, **k: {"prices": {}, "requests": 1, "blocked": None, "failed": {},
                                                             "hidden": {}, "last_us_trading_day": None, "monthly_unique_used": 0,
                                                             "new_symbols": 0})
    calls = []
    monkeypatch.setattr(mc, "fr6c_backfill_once", lambda cands, *a, **k: calls.append(cands) or {"requests": 0})
    monkeypatch.setattr(mc, "backfill_prices", lambda *a, **k: {"requests": 1, "blocked": None})
    mc.run("daily", get_tiingo=lambda *a, **k: None, today=TODAY)
    assert calls == [["ALT"]]
    monkeypatch.setattr(mc, "backfill_prices", lambda *a, **k: {"requests": 1, "blocked": "Tiingo HTTP 429"})
    mc.run("daily", get_tiingo=lambda *a, **k: None, today=TODAY)
    assert calls == [["ALT"]]
