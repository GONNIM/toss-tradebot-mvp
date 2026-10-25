"""실주문 · Kill Switch 알림 문구 (1023-05 Task 8)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.discovery.live_tape import entry as entry_mod
from backend.discovery.live_tape import exit as exit_mod
from backend.execution import kill_switch as ks
from backend.tests.alert_rules import violations


def test_entry_wording():
    cand = SimpleNamespace(tape_score=0.82, return_pct=0.064)
    title, body = entry_mod._entry_message("042700", "한미반도체", 53285.0, 19, cand, "3f9a2c1b-7e4d-1111")
    assert title == "🎯 실주문 · 한미반도체(042700) 삼"
    assert "53,285원 × 19주 (약 1,012,415원)" in body
    assert "거래 흐름 점수 0.82 · 오늘 +6.4%" in body
    assert "주문 번호 3f9a2c1b-7e4" in body
    assert violations(title, body) == []


def test_exit_reason_korean():
    title, body = exit_mod._exit_message("042700", "한미반도체", 53285.0, 52300.0, 19, -0.0185, "hard_sl", "3f9a2c1b-7e4d")
    assert title == "🏁 실주문 · 한미반도체(042700) 팔림 -1.85%"
    assert "산 값 53,285원 → 판 값 52,300원 · 19주" in body
    assert "이유: 손절선 도달" in body
    assert violations(title, body) == []


def test_exit_without_name_or_pnl():
    title, body = exit_mod._exit_message("042700", None, 53285.0, None, 19, None, "force_close", "abc")
    assert "042700 (종목명 확인 안 됨)" in title
    assert "None" not in title + body
    assert "장 마감 정리" in body


def test_kill_switch_wording():
    state = SimpleNamespace(reason="daily_loss_limit_reached(-3.12%)", activated_by="auto:sniper",
                            activated_at=datetime(2026, 10, 23, 1, 42, 10, tzinfo=timezone.utc))
    title, body = ks._kill_switch_message(state)
    assert title == "🚨 Kill Switch · 새 주문 모두 멈춤"
    assert "이유: 오늘 손실 한도 도달 (-3.12%)" in body
    assert "누가: 자동 (스나이퍼)" in body
    assert "시각: 10/23 10:42" in body
    assert "DELETE" not in body
    assert "풀기: https://optimus8.cafe24.com/sniper 의 「수동 해제」 (관리자 로그인)" in body
    assert violations(title, body) == []


def test_kill_switch_manual_actor_escaped():
    state = SimpleNamespace(reason="손으로 <정지>", activated_by="user:manual", activated_at=None)
    _, body = ks._kill_switch_message(state)
    assert "누가: 직접" in body and "&lt;정지&gt;" in body and "시각: —" in body
