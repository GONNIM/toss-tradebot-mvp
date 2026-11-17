"""1117-01 · 주식수 주간 단계가 요청 1건마다 하루 SEC 상한을 본다 (교훈 #12) · 가짜 종목만."""
from __future__ import annotations

import json
from datetime import date

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_mcap_daily as mc
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecDailyLedger

DAY = "20261012"


def _setup(tmp_path, monkeypatch, n, used):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setattr(mc, "load_candidates", lambda: {f"T{i:03d}": str(i + 1) for i in range(n)})
    monkeypatch.setattr(mc, "over5b_record", lambda: {})
    led = SecDailyLedger.load(DAY)
    if used:
        led.add("form4", used)
        led.save()


def _ok(url):
    return {"status": 200, "json": {"facts": {}}}


def _counts(tmp_path):
    return json.loads((tmp_path / "sec_usage" / f"sec_usage_{DAY}.json").read_text())


def test_stops_at_cap_and_defers_rest(tmp_path, monkeypatch, caplog):
    _setup(tmp_path, monkeypatch, 10, SEC_DAILY_CAP - 4)    # 남은 몫 4
    sent = []
    res = mc.run("weekly", get_sec=lambda u: sent.append(u) or _ok(u), today=date(2026, 10, 12))
    assert len(sent) == 4 and res["requests"] == 4 and res["deferred"] == 6
    led = _counts(tmp_path)
    assert led["total"] == SEC_DAILY_CAP and led["counts"]["mcap_shares"] == 4
    assert any("상한 도달" in r.message and "6" in r.message for r in caplog.records)
    # 받은 값으로 저장은 이어 감
    assert (tmp_path / "mcap" / f"shares_{DAY}.json").exists()


def test_already_at_cap_sends_nothing_but_still_saves(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 3, SEC_DAILY_CAP)
    res = mc.run("weekly", get_sec=lambda u: 1 / 0, today=date(2026, 10, 12))
    assert res["requests"] == 0 and res["deferred"] == 3
    assert _counts(tmp_path)["total"] == SEC_DAILY_CAP
    assert (tmp_path / "mcap" / f"shares_{DAY}.json").exists()


def test_room_enough_sends_all(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 5, 100)
    res = mc.run("weekly", get_sec=_ok, today=date(2026, 10, 12))
    assert res["requests"] == 5 and res["deferred"] == 0
    assert _counts(tmp_path)["total"] == 105


def test_exactly_fills_cap_not_over(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 5, SEC_DAILY_CAP - 5)
    res = mc.run("weekly", get_sec=_ok, today=date(2026, 10, 12))
    assert res["requests"] == 5 and res["deferred"] == 0 and _counts(tmp_path)["total"] == SEC_DAILY_CAP


def test_passed_ledger_object_counts_too(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 6, 0)
    led = SecDailyLedger.load(DAY)
    led.add("form4", SEC_DAILY_CAP - 2)
    res = mc.run("weekly", get_sec=_ok, today=date(2026, 10, 12), ledger=led)
    assert res["requests"] == 2 and res["deferred"] == 4 and led.total() == SEC_DAILY_CAP


def test_weekly_shares_without_gate_unchanged():
    res = mc.weekly_shares({"AAA": "1", "BBB": "2", "CCC": ""}, _ok, date(2026, 10, 12))
    assert res["requests"] == 2 and res["deferred"] == 0
