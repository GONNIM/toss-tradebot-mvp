"""WP75-2 · IEX 일괄 1회 · 오래된 timestamp 숨김 · 새 후보만 월 고유 등록 · 시간 단위 기록 · 원문 보관 · 플래그 꺼짐 0회."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from backend.scripts import biotech_h6_collect_prices as h6
from backend.scripts import biotech_mcap_daily as mc

KST = timezone(timedelta(hours=9))
KEY = "tk-test-" + "z" * 30


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


ROWS = [
    {"ticker": "AAA", "tngoLast": 10.0, "prevClose": 9.5, "timestamp": "2026-10-01T20:00:00+00:00"},
    {"ticker": "BBB", "tngoLast": 20.0, "prevClose": 19.0, "timestamp": "2026-10-01T20:00:00+00:00"},
    {"ticker": "CCC", "tngoLast": 3.0, "prevClose": 3.1, "timestamp": "2026-08-27T20:00:00+00:00"},   # 오래됨
]


def _setup(tmp_path, monkeypatch, used=None):
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    if used:
        h6.save_usage({"month": "202610", "symbols": {t: {"first_use": "2026-10-01", "by": "H6"} for t in used}})


def test_one_request_for_all_tickers_key_in_header(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = []

    def get(url, params=None, headers=None):
        seen.append((url, params, headers))
        return _R(200, ROWS)

    res = mc.daily_prices(["AAA", "BBB", "CCC"], KEY, get, date(2026, 10, 2),
                          now=lambda: datetime(2026, 10, 2, 7, 1, tzinfo=KST))
    assert len(seen) == 1 and res["requests"] == 1
    url, params, headers = seen[0]
    assert url.endswith("/iex/") and params == {"tickers": "AAA,BBB,CCC"}
    assert KEY not in url and KEY not in str(params) and headers["Authorization"] == f"Token {KEY}"
    saved = json.loads((tmp_path / "mcap" / "iex_20261002.json").read_text())
    assert saved == ROWS                                   # 응답 원문 보관
    usage = h6.load_usage("202610")
    assert usage["hourly"] == {"2026-10-02T07": {"WP75": 1}}


def test_stale_timestamp_hidden_last_day_is_mode(tmp_path, monkeypatch, caplog):
    import logging
    _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO)
    res = mc.daily_prices(["AAA", "BBB", "CCC"], KEY, lambda *a, **k: _R(200, ROWS), date(2026, 10, 2))
    assert res["last_us_trading_day"] == "2026-10-01"
    assert set(res["prices"]) == {"AAA", "BBB"} and res["hidden"] == {"CCC": "2026-08-27"}
    assert res["prices"]["AAA"] == {"close": 10.0, "close_date": "2026-10-01"}
    assert "가격 오래됨 · CCC · 2026-08-27" in caplog.text


def test_only_new_candidates_registered(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, used=["AAA"])            # AAA 는 이미 장부에 있음 (H6)
    res = mc.daily_prices(["AAA", "BBB", "CCC"], KEY, lambda *a, **k: _R(200, ROWS), date(2026, 10, 2))
    usage = h6.load_usage("202610")
    assert usage["symbols"]["AAA"]["by"] == "H6"            # 기존 등록 유지
    assert {t for t, v in usage["symbols"].items() if v["by"] == "WP75"} == {"BBB", "CCC"}
    assert res["new_symbols"] == 2 and res["monthly_unique_used"] == 3


def test_flag_off_zero_requests(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.delenv(mc.FLAG, raising=False)
    calls = []
    res = mc.run("daily", get_tiingo=lambda *a, **k: calls.append(1))
    assert res["skipped"] is True and calls == []
    assert not (tmp_path / "tiingo_usage_202610.json").exists()


def test_old_iex_files_pruned(tmp_path):
    (tmp_path / "iex_20260830.json").write_text("[]")
    (tmp_path / "iex_20260915.json").write_text("[]")
    assert mc.prune_iex(tmp_path, date(2026, 10, 2)) == 1
    assert not (tmp_path / "iex_20260830.json").exists() and (tmp_path / "iex_20260915.json").exists()
