"""WP75 · 시총 매일 산정 · 플래그 꺼짐 호출 0 · 12개월/60일 · 판정 입력 제외 · SEC 헤더 상수 · 429 중단."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from backend.scripts import biotech_mcap_daily as mc

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def test_flag_off_zero_calls(monkeypatch):
    monkeypatch.delenv(mc.FLAG, raising=False)
    calls = []
    for mode in ("daily", "weekly"):
        res = mc.run(mode, get_tiingo=lambda *a, **k: calls.append(1), get_sec=lambda u: calls.append(1))
        assert res["skipped"] is True
    assert calls == []


def test_badge_rule_12_months_and_60_days(tmp_path, monkeypatch):
    from backend.api.routes import biotech as b
    today = date.today()
    rows = {
        "OK": {"shares": 10_000_000, "shares_asof": (today - timedelta(days=100)).isoformat(), "close": 50, "close_date": (today - timedelta(days=1)).isoformat()},
        "OLDSH": {"shares": 10_000_000, "shares_asof": (today - timedelta(days=400)).isoformat(), "close": 50, "close_date": today.isoformat()},
        "OLDPX": {"shares": 10_000_000, "shares_asof": today.isoformat(), "close": 50, "close_date": (today - timedelta(days=61)).isoformat()},
    }
    (tmp_path / "mcap_display.json").write_text(json.dumps({"rows": rows}))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._MCAP_CACHE.update({"mtime": None, "rows": {}})
    assert b._mcap_display("OK")[0] == "300M-1B" and b._mcap_display("OK")[1] == rows["OK"]["close_date"]
    assert b._mcap_display("OLDSH") == ("", "") and b._mcap_display("OLDPX") == ("", "")


def test_mcap_not_in_decision_inputs():
    """후보 선정 · 시간 상태 · 커뮤니티 · 레이더 점수 스크립트는 시총 표시 파일을 읽지 않는다."""
    for name in ("biotech_h48v3_candidates.py", "biotech_h50_ct_upcoming.py", "biotech_h48v3_confirm.py", "biotech_h46v3_radar.py"):
        text = (SCRIPTS / name).read_text()
        for needle in ("mcap_display", "biotech_mcap_daily", "prices_2", "shares_2"):
            assert needle not in text, f"{name} 가 {needle} 를 참조"


def test_sec_header_constant_only():
    text = (SCRIPTS / "biotech_mcap_daily.py").read_text()
    assert "build_client()" in text and "User-Agent" not in text and "headers=" not in text


def test_sec_429_stops(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        return {"status": 429, "json": None}

    res = mc.weekly_shares({"AAA": "1", "BBB": "2"}, get, date(2026, 10, 5))
    assert res["blocked"] == "SEC HTTP 429" and len(calls) == 1


def test_tiingo_429_stops_and_ledger_shared(tmp_path, monkeypatch):
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    calls = []

    def get(url, params=None, headers=None):
        calls.append(url)
        return _R(429)

    res = mc.daily_prices(["AAA", "BBB"], "k" * 20, get, date(2026, 10, 2), sleep=lambda s: None)
    assert res["blocked"] and len(calls) == 1
    ledger = json.loads((tmp_path / "tiingo_usage_202610.json").read_text())
    assert ledger["symbols"]["AAA"]["by"] == "WP75"            # H6 과 같은 월 장부


def test_dei_only_shares():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-08-01", "val": 5, "accn": "a"}]}}},
                       "us-gaap": {"CommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-09-01", "val": 9, "accn": "b"}]}}}}}
    hit = mc.dei_shares(facts, "2026-10-05")
    assert hit["shares"] == 5 and hit["concept"] == "dei:EntityCommonStockSharesOutstanding"



def test_dei_multiple_classes_summed_but_not_across_filings():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-08-01", "val": 100, "accn": "Q2", "filed": "2026-08-05"},   # A 주
        {"end": "2026-08-01", "val": 40, "accn": "Q2", "filed": "2026-08-05"},    # B 주 (같은 공시)
        {"end": "2026-08-01", "val": 100, "accn": "Q2A", "filed": "2026-08-01"},  # 옛 공시 (합산 안 함)
        {"end": "2026-05-01", "val": 90, "accn": "Q1", "filed": "2026-05-05"},
    ]}}}}}
    hit = mc.dei_shares(facts, "2026-10-05")
    assert hit["shares"] == 140 and hit["n_values"] == 2 and hit["accn"] == "Q2" and hit["asof"] == "2026-08-01"
