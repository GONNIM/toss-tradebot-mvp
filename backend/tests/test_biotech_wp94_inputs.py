"""WP94 · 레이더 입력 부재 가시화 · 없음 → 5개 · 텔레그램 1회 / 있음 → 빈 목록."""
from __future__ import annotations

from pathlib import Path

from backend.scripts import biotech_h46v3_radar as radar


def test_all_missing_lists_five_and_notifies_once(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(radar._P, "find", lambda *a, **k: None)
    monkeypatch.setattr(radar._P, "find_glob", lambda *a, **k: None)
    sent = []
    missing = radar.check_inputs("abc1234", notify=lambda t, b: sent.append((t, b)))
    assert missing == ["h6_membership", "h3_events", "h57_pubmed_index", "h58_preprint_index", "h3_prices_merged"]
    assert len(sent) == 1 and all(n in sent[0][1] for n in missing)
    assert caplog.text.count("레이더 입력 없음") == 5


def test_all_present_empty_list_no_notify(monkeypatch):
    monkeypatch.setattr(radar._P, "find", lambda *a, **k: Path("/x"))
    sent = []
    assert radar.check_inputs("abc1234", notify=lambda t, b: sent.append(1)) == [] and sent == []


def test_api_reads_inputs_missing_from_csv(tmp_path):
    from backend.api.routes import biotech as api
    p = tmp_path / "radar_v1_3_20261002.csv"
    p.write_text("ticker,score,inputs_missing\nAAA,0.5,h3_events|h3_prices_merged\n")
    assert api._radar_inputs_missing(p) == ["h3_events", "h3_prices_merged"]
    old = tmp_path / "radar_v1_3_20261001.csv"
    old.write_text("ticker,score\nAAA,0.5\n")
    assert api._radar_inputs_missing(old) == []


def test_notify_once_per_day_and_off_switch(tmp_path, monkeypatch):
    monkeypatch.setattr(radar._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(radar._P, "find", lambda *a, **k: None)
    monkeypatch.setattr(radar._P, "find_glob", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(radar, "_notify_warning", lambda t, b: sent.append(t))
    monkeypatch.delenv("BIOTECH_NOTIFY_OFF", raising=False)
    radar.check_inputs("s")
    radar.check_inputs("s")                     # 같은 날 두 번째 실행
    assert len(sent) == 1
    monkeypatch.setenv("BIOTECH_NOTIFY_OFF", "1")
    for f in (tmp_path / "logs").glob("radar_inputs_warned_*"):
        f.unlink()
    radar.check_inputs("s")
    assert len(sent) == 1                       # 로컬 확인 실행은 알림 없음
