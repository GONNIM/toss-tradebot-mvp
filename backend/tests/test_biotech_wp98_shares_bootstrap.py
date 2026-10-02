"""WP98 · mcap 일일 단계 · 주식수 파일이 없으면 주간 주식수 조회 1회 · 있으면 0회."""
from __future__ import annotations

import json
from datetime import date

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_mcap_daily as mc

TODAY = date(2026, 10, 3)


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setenv("TIINGO_API_KEY", "tk-test-" + "z" * 30)
    monkeypatch.setattr(mc, "load_candidates", lambda: {"AAA": "1", "BBB": "2"})
    monkeypatch.setattr(mc, "backfill_prices", lambda *a, **k: {"requests": 0})
    iex = [{"ticker": "AAA", "tngoLast": 5.0, "timestamp": "2026-10-02T20:00:00+00:00"}]
    return lambda *a, **k: _R(200, iex)


def test_no_shares_file_runs_weekly_once(tmp_path, monkeypatch):
    get_tiingo = _setup(tmp_path, monkeypatch)
    sec = []
    mc.run("daily", get_tiingo=get_tiingo, get_sec=lambda u: sec.append(u) or {"status": 404, "json": None}, today=TODAY)
    assert len(sec) == 2 and list((tmp_path / "mcap").glob("shares_*.json"))
    led = json.loads((tmp_path / "sec_usage" / "sec_usage_20261003.json").read_text())
    assert led["counts"] == {"mcap_shares": 2}


def test_existing_shares_file_no_sec(tmp_path, monkeypatch):
    get_tiingo = _setup(tmp_path, monkeypatch)
    (tmp_path / "mcap").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mcap" / "shares_20261001.json").write_text(json.dumps({"shares": {"AAA": {"shares": 1, "shares_asof": "2026-09-30"}}}))
    sec = []
    mc.run("daily", get_tiingo=get_tiingo, get_sec=lambda u: sec.append(u) or {"status": 404, "json": None}, today=TODAY)
    assert sec == []


def test_ledger_unions_local_seed(tmp_path, monkeypatch):
    from backend.scripts import biotech_h6_collect_prices as h6
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "tiingo_usage_seed_202610.json").write_text(json.dumps({"symbols": {"AAA": {"by": "H6"}, "ZZZ": {"by": "WP75"}}}))
    monkeypatch.setattr(h6, "SEED_DIR", docs)
    h6.save_usage({"month": "202610", "symbols": {"AAA": {"by": "WP75"}, "BBB": {"by": "WP75"}}})
    u = h6.load_usage("202610")
    assert set(u["symbols"]) == {"AAA", "BBB", "ZZZ"} and u["symbols"]["AAA"]["by"] == "WP75"   # 서버 기록 우선 · 합집합
