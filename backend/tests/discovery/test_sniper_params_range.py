"""1030-06 Fable 권고: SniperParams 값 범위 검사."""
import json

import pytest

from backend.discovery.live_tape.params import SniperParams, SniperParamsStore


def test_defaults_pass():
    SniperParams()


def test_prod_snapshot_passes():
    """11/02 운영 sniper_params.json 값 (force_close_enabled False) 이 통과해야 배포 뒤 기본값으로 떨어지지 않는다."""
    SniperParams(force_close_enabled=False)


@pytest.mark.parametrize("kw", [
    {"hard_stop_loss_pct": 0.03},
    {"daily_loss_limit_pct": 3},
    {"per_order_krw": 2_000_000.0},
    {"active_start_kst": "25:00"},
    {"active_start_kst": "15:30"},
    {"rank_target_min": 60},
    {"poll_rankings_sec": 0},
    {"watchlist_min_composite_score": 1.5},
    {"entry_return_min_pct": 0.1},
])
def test_bad_values_rejected(kw):
    with pytest.raises(ValueError):
        SniperParams(**kw)


def test_patch_rejects_and_keeps_file(tmp_path):
    store = SniperParamsStore(tmp_path / "p.json")
    store.save(SniperParams())
    with pytest.raises(ValueError):
        store.patch({"hard_stop_loss_pct": 0.05})
    assert json.loads((tmp_path / "p.json").read_text())["hard_stop_loss_pct"] == -0.03


def test_bad_file_falls_back_to_default(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"hard_stop_loss_pct": 0.05, "enabled": True}))
    got = SniperParamsStore(p).get()
    assert got.enabled is False and got.hard_stop_loss_pct == -0.03
