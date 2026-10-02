"""WP98-3 · 자동 분류 (용어 하나 예외 → 계속 · 캐시 중간 저장) · SEC 상한 (13D 등록부 · 같은 날 주식수 건너뜀)."""
from __future__ import annotations

import json
from datetime import date

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_auto_category as ac
from backend.scripts import biotech_mcap_daily as mc
from backend.scripts import biotech_radar_inputs_weekly as wk
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecDailyLedger


class _FakeClient:
    def __init__(self, fail_on: set[str]):
        self.fail_on, self.requests = fail_on, 0

    def trees(self, term):
        self.requests += 1
        if term in self.fail_on:
            raise ConnectionError("boom")
        return {"descriptor": "D1", "trees": [], "method": "descriptor"}


def _snap(n):
    return {"matches": [{"ticker": "AAA", "conditions": [f"Term {i:03d}" for i in range(n)], "mesh_terms": []}]}


def test_one_term_error_continues_and_is_retried_next_time():
    cache = {}
    auto, rows, st = ac.build(_snap(5), set(), cache, [], _FakeClient({"Term 002"}), "20261002")
    assert st["skipped_terms"] == 1 and "Term 002" not in cache and len(cache) == 4
    client2 = _FakeClient(set())
    ac.build(_snap(5), set(), cache, [], client2, "20261003")
    assert client2.requests == 1 and "Term 002" in cache                  # 건너뛴 용어만 다시 시도


def test_cache_saved_every_50_and_on_exit():
    saves = []
    cache = {}
    ac.build(_snap(120), set(), cache, [], _FakeClient(set()), "20261002", save=lambda: saves.append(len(cache)))
    assert saves == [50, 100, 120]                                        # 50 · 100 · 끝


def test_13d_registry_deferred_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(wk, "load_registry", lambda: [{"cik": str(i), "institution": "x"} for i in range(5)])
    led = SecDailyLedger.load("20261002")
    led.add("form4", SEC_DAILY_CAP - 2)
    led.save()
    calls = []

    class _H:
        status_code, text = 200, ""

        def json(self):
            return {"filings": {"recent": {}}}

    res = wk.run_13d(get=lambda u: calls.append(u) or _H(), today=date(2026, 10, 2))
    assert len(calls) == 2 and res["deferred_registry"] == 3
    assert json.loads((tmp_path / "sec_usage" / "sec_usage_20261002.json").read_text())["total"] == SEC_DAILY_CAP


def test_weekly_shares_skipped_when_today_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setattr(mc, "load_candidates", lambda: {"AAA": "1"})
    (tmp_path / "mcap").mkdir()
    (tmp_path / "mcap" / "shares_20261002.json").write_text("{}")
    sec = []
    res = mc.run("weekly", get_sec=lambda u: sec.append(u), today=date(2026, 10, 2))
    assert res["skipped"] is True and sec == []
