"""WP86 · 배수 기준선 하한 · 경보 조건 무변경 · SEC 명부 런타임 우선 · 주간 갱신 실패 시 기존 유지."""
from __future__ import annotations

import json

from backend.scripts.biotech_alert_rule import judge
from backend.scripts.biotech_h48v3_confirm import baseline_multiple


def _row(mean, today, n=8, rss=0):
    return {"st_baseline_n": str(n), "st_baseline_mult": str(baseline_multiple(today, mean)),
            "apewisdom_24h": str(today), "reddit_rss_matches": str(rss)}


def test_mean_zero_today_14_is_14x_alert():
    assert baseline_multiple(14, 0.0) == 14.0
    assert judge(_row(0.0, 14)) == (True, "mult")          # KOD 9/29 형태 · 이전에는 배수 없음으로 누락


def test_mean_quarter_today_32_is_32x():
    assert baseline_multiple(32, 0.25) == 32.0             # IOVA 9/30 · 이전 128배
    assert judge(_row(0.25, 32)) == (True, "mult")


def test_mean_3_today_12_is_4x_no_alert():
    assert baseline_multiple(12, 3.0) == 4.0
    assert judge(_row(3.0, 12)) == (False, "none")


def test_api_prefers_runtime_sec_tickers(tmp_path, monkeypatch):
    from backend.api.routes import biotech as b
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps({"0": {"cik_str": 2088082, "ticker": "NEWT", "title": "x"}}))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    assert b._cik_ticker_map()["0002088082"] == "NEWT"      # 런타임 (주간 갱신) 이 docs 이식본 (ETRA) 보다 우선


def test_weekly_refresh_keeps_existing_on_429(tmp_path, monkeypatch):
    from backend.scripts import _biotech_paths as _P
    from backend.scripts import biotech_h69_aact_weekly as w
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    old = tmp_path / "sec_company_tickers.json"
    old.write_text('{"keep": 1}')
    res = w.refresh_sec_company_tickers(get=lambda url: {"status": 429, "json": None})
    assert res["updated"] is False and old.read_text() == '{"keep": 1}'
