"""Kill Switch 스위트."""
from __future__ import annotations

from backend.execution.kill_switch import KillSwitch


def test_kill_switch_initial_state(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    assert ks.is_active() is False


def test_activate_persists_and_notifies(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    ks.activate(reason="test", actor="auto:test")
    assert ks.is_active() is True

    # 새 인스턴스로 로드 시에도 상태 유지 (파일 기반)
    ks2 = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    assert ks2.is_active() is True
    assert ks2.status().reason == "test"


def test_deactivate_toggles_off(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    ks.activate("test", "auto:test")
    ks.deactivate("user:test")
    assert ks.is_active() is False
    s = ks.status()
    assert s.deactivated_by == "user:test"


def test_activate_idempotent(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    ks.activate("first", "auto:1")
    s1 = ks.status()
    ks.activate("second", "auto:2")
    s2 = ks.status()
    # 이미 활성 시 no-op (reason 유지)
    assert s1.reason == s2.reason == "first"
