"""2026-10-02 · mcap_display.json 이 행 0 개면 예전 입력 (mcap_display_inputs_*.csv) 으로 배지 표시."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backend.api.routes import biotech as api


def _setup(tmp_path, monkeypatch, runtime_rows):
    rt = tmp_path / "rt"
    rt.mkdir()
    (rt / "mcap_display.json").write_text(json.dumps({"generated": "2026-10-02", "rows": runtime_rows}))
    docs = tmp_path / "docs"
    docs.mkdir()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    (docs / "mcap_display_inputs_x.csv").write_text(
        "ticker,shares,shares_asof,close,close_date\nAAA,100000000,%s,5.0,%s\n" % (today.isoformat(), (today - timedelta(days=2)).isoformat()))
    monkeypatch.setattr(api, "DATA_DIR_RUNTIME", rt)
    monkeypatch.setattr(api, "DATA_DIR_DOCS", docs)
    monkeypatch.setattr(api, "_MCAP_CACHE", {"mtime": None, "rows": {}})


def test_empty_runtime_file_falls_back_to_previous_inputs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {})
    label, asof = api._mcap_display("AAA")
    assert label and asof


def test_nonempty_runtime_file_wins(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"BBB": {"shares": 1, "shares_asof": "2026-10-01", "close": 1, "close_date": "2026-10-01"}})
    assert api._mcap_display("AAA") == ("", "")
