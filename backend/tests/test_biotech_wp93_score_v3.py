"""WP93 · 레이더 점수 v3 · H6 소속 +3 제거 (v2 는 재계산용으로 남음)."""
from __future__ import annotations

from backend.scripts import biotech_h46v3_radar as radar


def test_v3_has_no_h6_membership_bonus():
    assert radar.SCORE_VERSION == "v3"
    member, outsider = radar.expert_channel_1_2(2, True), radar.expert_channel_1_2(2, False)
    assert member - outsider == 0.0                               # v3 · 소속 여부로 차이 없음
    assert radar.expert_channel_1_2(2, True, "v2") - radar.expert_channel_1_2(2, False, "v2") == 3.0   # v2 재계산


def test_screen_ignores_recompute_files(tmp_path, monkeypatch):
    from backend.api.routes import biotech as api
    d = tmp_path / "candidates"
    d.mkdir()
    (d / "radar_v1_3_20261001.csv").write_text("ticker\n")
    (d / "radar_v1_3_20261001_scorev2.csv").write_text("ticker\n")
    monkeypatch.setattr(api, "_search_dirs", lambda sub: [d])
    assert api._latest_radar_csv().name == "radar_v1_3_20261001.csv"
