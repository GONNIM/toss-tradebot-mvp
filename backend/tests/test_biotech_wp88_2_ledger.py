"""WP88-2 · 주간 잡 SEC 요청도 하루 공용 장부에 · h65 클라이언트 = build_client 헤더 · 상한 300."""
from __future__ import annotations

import json
from datetime import date

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_h65_form4_daily as h65
from backend.scripts import biotech_h69_aact_weekly as w
from backend.scripts import biotech_mcap_daily as mc
from backend.scripts.biotech_sec_common import REQ_INTERVAL, SEC_DAILY_CAP, SecDailyLedger, build_client


def _ledger(tmp_path, day):
    return json.loads((tmp_path / "sec_usage" / f"sec_usage_{day}.json").read_text())


def test_cap_300_interval_unchanged():
    assert SEC_DAILY_CAP == 300 and REQ_INTERVAL == 0.5


def test_company_tickers_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    body = {str(i): {"cik_str": i, "ticker": f"T{i}", "title": "x"} for i in range(1200)}
    led = SecDailyLedger.load("20261005")
    res = w.refresh_sec_company_tickers(get=lambda url: {"status": 200, "json": body}, ledger=led)
    assert res["updated"] is True
    assert _ledger(tmp_path, "20261005")["counts"] == {"company_tickers": 1}


def test_mcap_shares_counted_and_zero_when_off(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    # 플래그 꺼짐 → 0회로 남음
    monkeypatch.delenv(mc.FLAG, raising=False)
    mc.run("weekly", get_sec=lambda u: 1 / 0, today=date(2026, 10, 5))
    assert _ledger(tmp_path, "20261005")["counts"] == {"mcap_shares": 0}
    # 플래그 켜짐 → 보낸 요청 수 (CIK 있는 종목 2개)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setattr(mc, "load_candidates", lambda: {"AAA": "1", "BBB": "2", "CCC": ""})
    mc.run("weekly", get_sec=lambda u: {"status": 404, "json": None}, today=date(2026, 10, 12))
    assert _ledger(tmp_path, "20261012")["counts"] == {"mcap_shares": 2}


def test_h65_client_headers_same_as_build_client():
    ref = build_client()
    c = h65.sec_client(lambda req: None)
    try:
        for k in ("User-Agent", "From", "Accept-Encoding"):
            assert c.headers[k] == ref.headers[k]
        assert len(c.event_hooks["request"]) == 1
    finally:
        c.close()
        ref.close()
