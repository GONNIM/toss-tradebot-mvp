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


# ── 1117-01 ㉠① · 못 받은 종목은 직전 값과 원래 기준일을 옮겨 담음 ─────────────

def _prev_file(tmp_path, shares, day="20261005"):
    d = tmp_path / "mcap"
    d.mkdir(exist_ok=True)
    (d / f"shares_{day}.json").write_text(json.dumps({"date": "2026-10-05", "shares": shares}))


def _ok_with_shares(url):
    return {"status": 200, "json": {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-09-30", "val": 777, "accn": "A-NEW", "filed": "2026-11-01"}]}}}}}}


def _saved(tmp_path, day=DAY):
    return json.loads((tmp_path / "mcap" / f"shares_{day}.json").read_text())["shares"]


def test_carry_forward_keeps_original_asof_and_marks(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 4, SEC_DAILY_CAP - 2)               # T000 · T001 만 받음
    old = {f"T{i:03d}": {"cik": str(i + 1), "shares": 100 + i, "shares_asof": "2026-06-30", "accn": "A-OLD", "n_values": 1} for i in range(4)}
    _prev_file(tmp_path, old)
    res = mc.run("weekly", get_sec=_ok_with_shares, today=date(2026, 10, 12))
    sh = _saved(tmp_path)
    assert res["deferred"] == 2
    assert json.loads((tmp_path / "mcap" / f"shares_{DAY}.json").read_text())["carried"] == 2
    assert sh["T000"]["shares"] == 777 and "carried_from" not in sh["T000"]           # 새로 받은 값
    assert sh["T002"]["shares"] == 102 and sh["T002"]["shares_asof"] == "2026-06-30"  # 기준일 그대로
    assert sh["T002"]["carried_from"] == "2026-10-05" and sh["T003"]["carried_from"] == "2026-10-05"


def test_carry_forward_empty_when_no_previous_file_or_ticker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 3, SEC_DAILY_CAP - 1)
    mc.run("weekly", get_sec=_ok_with_shares, today=date(2026, 10, 12))
    assert set(_saved(tmp_path)) == {"T000"}                                          # 이전 파일 없음 → 비워 둠
    (tmp_path / "mcap" / f"shares_{DAY}.json").unlink()
    _prev_file(tmp_path, {"T001": {"cik": "2", "shares": 5, "shares_asof": "2026-03-31", "accn": "x", "n_values": 1}})
    (tmp_path / "sec_usage" / f"sec_usage_{DAY}.json").unlink()
    led = SecDailyLedger.load(DAY)
    led.add("form4", SEC_DAILY_CAP - 1)
    led.save()
    mc.run("weekly", get_sec=_ok_with_shares, today=date(2026, 10, 12))
    assert set(_saved(tmp_path)) == {"T000", "T001"}                                  # 이전 파일에 있는 것만 옮김


def test_carried_value_replaced_by_next_successful_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, 2, SEC_DAILY_CAP - 1)
    _prev_file(tmp_path, {"T001": {"cik": "2", "shares": 5, "shares_asof": "2026-03-31", "accn": "x", "n_values": 1}})
    mc.run("weekly", get_sec=_ok_with_shares, today=date(2026, 10, 12))
    assert _saved(tmp_path)["T001"]["carried_from"] == "2026-10-05"
    mc.run("weekly", get_sec=_ok_with_shares, today=date(2026, 10, 19))             # 다음 주 · 장부가 비어 전부 받음
    nxt = _saved(tmp_path, "20261019")
    assert nxt["T001"]["shares"] == 777 and "carried_from" not in nxt["T001"]


def test_carried_keeps_first_origin_on_second_carry(tmp_path):
    _prev_file(tmp_path, {"T001": {"cik": "2", "shares": 5, "shares_asof": "2026-03-31", "accn": "x", "n_values": 1,
                                   "carried_from": "2026-09-28"}})
    res = {}
    assert mc.carry_forward(res, ["T001"], tmp_path / "mcap", date(2026, 10, 12)) == 1
    assert res["T001"]["carried_from"] == "2026-09-28"


def test_display_row_and_api_badge_show_original_asof(tmp_path, monkeypatch):
    from backend.api.routes import biotech as api
    shares = {"T001": {"shares": 1000, "shares_asof": "2026-03-31", "carried_from": "2026-10-05"},
              "T002": {"shares": 1000, "shares_asof": "2026-06-30"}}
    today = date.today().isoformat()
    prices = {k: {"close": 1.0, "close_date": today} for k in shares}
    disp = mc.build_display(shares, prices)
    assert disp["T001"]["carried_from"] == "2026-10-05" and "carried_from" not in disp["T002"]
    (tmp_path / "mcap_display.json").write_text(json.dumps({"rows": disp}))
    monkeypatch.setattr(api, "DATA_DIR_RUNTIME", tmp_path)
    monkeypatch.setattr(api, "MCAP_SHARES_MAX_AGE_DAYS", 10**6)
    api._MCAP_CACHE.update(mtime=None, rows={})
    bucket, asof = api._mcap_display("T001")
    assert bucket and asof == today and api._mcap_shares_carried("T001") == "2026-03-31"
    api._mcap_display("T002")
    assert api._mcap_shares_carried("T002") == "" and api._mcap_shares_carried("NONE") == ""
