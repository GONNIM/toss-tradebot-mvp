"""Kill Switch 스위트."""
from __future__ import annotations

import json

from backend.execution.kill_switch import KillSwitch
from backend.execution.models import OrderSide


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


# ─── 1105-02 · 켜진 동안 매도 허용 (sell_allowed) ───
def test_blocks_by_side(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    assert ks.blocks(OrderSide.BUY) is False and ks.blocks(OrderSide.SELL) is False
    ks.activate("t", "auto:test")
    assert ks.blocks(OrderSide.BUY) is True
    assert ks.blocks(OrderSide.SELL) is False
    assert ks.blocks("sell") is False


def test_old_state_file_without_field_allows_sell(tmp_paths):
    path = tmp_paths["kill_switch"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active": True, "reason": "old", "activated_at": "2026-11-01T00:00:00+00:00",
                                "activated_by": "auto:sniper", "deactivated_at": None, "deactivated_by": None}))
    ks = KillSwitch(state_path=path, notifier=None)
    assert ks.status().sell_allowed is True
    assert ks.blocks(OrderSide.SELL) is False and ks.blocks(OrderSide.BUY) is True


def test_narrow_to_stop_sells_persists(tmp_paths):
    sent = []

    class _N:
        async def send_critical(self, title, body, category=None):
            sent.append(title)
            return True

    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=_N())
    ks.activate("daily_loss_limit_reached(-3.10%)", "auto:sniper")
    s = ks.activate("보유 종목 매도도 멈춤", "user:manual", sell_allowed=False)
    assert s.active is True and s.sell_allowed is False
    assert s.activated_by == "auto:sniper"                    # 처음 발동 기록은 그대로
    assert "daily_loss_limit_reached(-3.10%)" in s.reason and "매도도 멈춤" in s.reason
    assert ks.blocks(OrderSide.SELL) is True
    assert len(sent) == 2 and "모든 주문 멈춤" in sent[1]
    # 다시 읽어도 유지 (Fable 1105-02-02 권고 3)
    ks2 = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    assert ks2.status().sell_allowed is False
    # 켜진 상태에서 True 재요청 → 그대로 False
    assert ks2.activate("again", "user:manual", sell_allowed=True).sell_allowed is False
    # 이미 False 에서 False 재요청 → 알림 없음
    ks.activate("again", "user:manual", sell_allowed=False)
    assert len(sent) == 2


def test_reactivate_after_deactivate_can_allow_sell_again(tmp_paths):
    ks = KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)
    ks.activate("a", "user:manual", sell_allowed=False)
    ks.deactivate("user:manual")
    assert ks.blocks(OrderSide.SELL) is False
    ks.activate("b", "user:manual")
    assert ks.status().sell_allowed is True
