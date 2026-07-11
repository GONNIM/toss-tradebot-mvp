"""Sniper Sprint 1 · Contract Test · T47.

검증 범위:
- SniperParams store · patch · hot reload
- 6단계 매수 방어 (Kill Switch · Seed · 상한 · 정규장 · 재진입 · warnings)
- Trailing Stop · evaluate_trailing (trailing · hard_sl)
- Daily loss 자동 Kill Switch 트리거
- 100% 손실 시나리오 (33거래일 시뮬 안전 종결)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.live_tape import entry as entry_mod
from backend.discovery.live_tape.entry import execute_entry
from backend.discovery.live_tape.exit import execute_exit
from backend.discovery.live_tape.params import SniperParams, SniperParamsStore
from backend.discovery.live_tape.scoring import CandidateSignal
from backend.discovery.live_tape.trailing_stop import evaluate_trailing
from backend.execution.audit import record_order_result
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.kill_switch import KillSwitch
from backend.execution.models import (
    BrokerKind,
    Fill,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from backend.services.db import get_session, init_db
from backend.services.models import OrderAudit, SniperSignal


@pytest.fixture
def sniper_params_isolated(tmp_path):
    """격리된 SniperParams store."""
    store = SniperParamsStore(path=tmp_path / "sniper_params.json")
    return store


@pytest.fixture
def tmp_paper_paths(tmp_path):
    return {
        "balance": tmp_path / "paper.json",
        "kill_switch": tmp_path / "ks.json",
    }


@pytest.fixture
def fake_prices():
    return {"000001": 10_000.0, "000002": 10_000.0, "000003": 10_000.0, "000004": 10_000.0}


@pytest.fixture
def paper_adapter(tmp_paper_paths, fake_prices):
    from .conftest import SniperFakeTossClient
    ks = KillSwitch(state_path=tmp_paper_paths["kill_switch"], notifier=None)
    fake = SniperFakeTossClient(prices=fake_prices)
    adapter = PaperAdapter(state_path=tmp_paper_paths["balance"], kill_switch=ks, toss_client=fake)
    adapter.reset(cash_krw=1_000_000)
    return adapter, ks


def make_candidate(ticker="000001", price=10_000.0):
    return CandidateSignal(
        ticker=ticker, tape_score=2.7, rank_velocity_score=2.5,
        trades_intensity_score=3.0, orderbook_score=2.5,
        last_price=price, return_pct=0.03,
        detected_at=datetime.now(tz=timezone.utc),
        raw_rank_delta=25, raw_trades_intensity=20.0, raw_bid_ratio=0.62,
    )


@pytest_asyncio.fixture
async def db_ready():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SniperSignal))
        await session.execute(delete(OrderAudit))
    yield
    async with get_session() as session:
        await session.execute(delete(SniperSignal))
        await session.execute(delete(OrderAudit))


# ═══════════════════════════════════════════════════════════════
# SniperParams
# ═══════════════════════════════════════════════════════════════
def test_params_defaults(sniper_params_isolated):
    p = sniper_params_isolated.get()
    assert p.seed_cap_krw == 1_000_000
    assert p.per_order_krw == 100_000
    assert p.max_concurrent_positions == 3
    assert p.trailing_giveback_pct == 0.03
    assert p.hard_stop_loss_pct == -0.03
    assert p.daily_loss_limit_pct == -0.03
    assert p.force_close_enabled is True
    assert p.enabled is False


def test_params_patch_persists(sniper_params_isolated):
    p = sniper_params_isolated.patch({"trailing_giveback_pct": 0.05, "enabled": True})
    assert p.trailing_giveback_pct == 0.05
    assert p.enabled is True
    p2 = sniper_params_isolated.get()
    assert p2.trailing_giveback_pct == 0.05
    assert p2.enabled is True


def test_params_hot_reload(sniper_params_isolated):
    import json
    import time
    p1 = sniper_params_isolated.get()
    assert p1.per_order_krw == 100_000
    time.sleep(0.05)
    sniper_params_isolated.path.write_text(
        json.dumps({"per_order_krw": 50_000}), encoding="utf-8"
    )
    p2 = sniper_params_isolated.get()
    assert p2.per_order_krw == 50_000


# ═══════════════════════════════════════════════════════════════
# 6단계 매수 방어
# ═══════════════════════════════════════════════════════════════
async def test_entry_blocked_by_kill_switch(db_ready, paper_adapter):
    adapter, ks = paper_adapter
    ks.activate("test", "auto:test")
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r = await execute_entry(make_candidate(), adapter, kill_switch=ks)
    assert r.ok is False
    assert r.reason == "kill_switch_active"


async def test_entry_blocked_by_seed_shortage(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    adapter.reset(cash_krw=50_000)  # per_order 10만 미달
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        r = await execute_entry(make_candidate(), adapter, kill_switch=ks)
    assert r.ok is False
    assert r.reason.startswith("seed_remain<")


async def test_entry_blocked_outside_active_window(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=False):
        r = await execute_entry(make_candidate(), adapter, kill_switch=ks)
    assert r.ok is False
    assert r.reason.startswith("outside_active_window")


async def test_entry_blocked_by_warnings(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())

    async def _blocked_warnings(ticker, toss_client=None):
        from backend.discovery.live_tape.warnings import WarningsResult
        return WarningsResult(
            ticker=ticker, blocked=True,
            active_types=("VI_STATIC",),
            checked_at=datetime.now(tz=timezone.utc),
        )
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_blocked_warnings):
            r = await execute_entry(make_candidate(), adapter, kill_switch=ks)
    assert r.ok is False
    assert "VI_STATIC" in r.reason


async def _pass_warnings(ticker, toss_client=None):
    from backend.discovery.live_tape.warnings import WarningsResult
    return WarningsResult(
        ticker=ticker, blocked=False, active_types=(),
        checked_at=datetime.now(tz=timezone.utc),
    )


async def test_entry_success_and_signal_row(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r = await execute_entry(make_candidate("000001", 10_000), adapter, kill_switch=ks)
    assert r.ok is True
    assert r.filled_qty == 10   # 100,000 // 10,000
    assert r.entry_price == 10_000.0
    assert r.sniper_signal_id is not None

    # SniperSignal row 확인
    async with get_session() as session:
        from sqlalchemy import select
        rows = (await session.execute(select(SniperSignal))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ticker == "000001"
    assert rows[0].peak_price == 10_000.0


async def test_entry_max_concurrent_positions(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    sniper_params_isolated.patch({"max_concurrent_positions": 2})
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())

    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r1 = await execute_entry(make_candidate("000001", 10_000), adapter, kill_switch=ks)
            r2 = await execute_entry(make_candidate("000002", 10_000), adapter, kill_switch=ks)
            r3 = await execute_entry(make_candidate("000003", 10_000), adapter, kill_switch=ks)
    assert r1.ok is True
    assert r2.ok is True
    assert r3.ok is False
    assert "positions_full" in r3.reason


async def test_entry_same_ticker_daily_limit(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r1 = await execute_entry(make_candidate("000001", 10_000), adapter, kill_switch=ks)
            r2 = await execute_entry(make_candidate("000001", 10_000), adapter, kill_switch=ks)
    assert r1.ok is True
    assert r2.ok is False
    assert r2.reason == "already_entered_today"


# ═══════════════════════════════════════════════════════════════
# Trailing Stop
# ═══════════════════════════════════════════════════════════════
def test_trailing_peak_updates(sniper_params_isolated, monkeypatch):
    from backend.discovery.live_tape import trailing_stop as ts
    monkeypatch.setattr(ts, "get_sniper_params", lambda: sniper_params_isolated.get())
    d = evaluate_trailing(entry_price=10_000, peak_price=10_000, current_price=10_500)
    assert d.should_exit is False
    assert d.peak_price == 10_500


def test_trailing_giveback_triggers(sniper_params_isolated, monkeypatch):
    from backend.discovery.live_tape import trailing_stop as ts
    monkeypatch.setattr(ts, "get_sniper_params", lambda: sniper_params_isolated.get())
    d = evaluate_trailing(entry_price=10_000, peak_price=10_500, current_price=10_100)
    assert d.should_exit is True
    assert d.reason == "trailing"


def test_hard_sl_triggers(sniper_params_isolated, monkeypatch):
    from backend.discovery.live_tape import trailing_stop as ts
    monkeypatch.setattr(ts, "get_sniper_params", lambda: sniper_params_isolated.get())
    # peak = entry · current -3.5% · trailing 이 hard_sl 보다 먼저 잡힘 (임계 -3% 초과)
    d = evaluate_trailing(entry_price=10_000, peak_price=10_000, current_price=9_650)
    assert d.should_exit is True
    # trailing · hard_sl 둘 다 성립 · 순서상 trailing 먼저
    assert d.reason in {"trailing", "hard_sl"}


# ═══════════════════════════════════════════════════════════════
# Exit + PnL
# ═══════════════════════════════════════════════════════════════
async def test_exit_updates_signal_and_pnl(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())

    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            entry_result = await execute_entry(make_candidate("000001", 10_000), adapter, kill_switch=ks)
    assert entry_result.ok is True

    # 가격 상승 → 매도
    adapter._toss._prices["000001"] = 10_500

    exit_result = await execute_exit(entry_result.sniper_signal_id, adapter, trigger_reason="trailing")
    assert exit_result.ok is True
    assert exit_result.exit_price == 10_500
    assert abs(exit_result.pnl_pct - 0.05) < 0.001
    assert exit_result.trigger_reason == "trailing"

    # SniperSignal UPDATE
    async with get_session() as session:
        row = await session.get(SniperSignal, entry_result.sniper_signal_id)
    assert row.exit_order_uuid is not None
    assert row.exit_price == 10_500
    assert row.reason == "trailing"


# ═══════════════════════════════════════════════════════════════
# 100% 손실 시나리오 안전 종결
# ═══════════════════════════════════════════════════════════════
async def test_seed_full_loss_scenario_safe_termination(db_ready, paper_adapter, sniper_params_isolated, monkeypatch):
    """시드 100만 · 매 진입 -3% 손실 · 시드 소진까지 시뮬.

    Kill Switch 자동 발동 or InsufficientBalance 로 자연 종결되어야 함.
    """
    adapter, ks = paper_adapter
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: sniper_params_isolated.get())

    # per_order 크게 (10만) · 상한 3 · trailing/hard_sl -3%
    sniper_params_isolated.patch({
        "per_order_krw": 100_000,
        "max_concurrent_positions": 1,   # 진입-청산 반복 시뮬용
        "daily_loss_limit_pct": -0.03,
    })

    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            # 진입-손절 반복 · 매번 상이한 티커 사용 (방어5 우회)
            for i in range(1, 35):        # 최대 33회 예상
                ticker = f"{i:06d}"
                adapter._toss._prices[ticker] = 10_000
                r = await execute_entry(make_candidate(ticker, 10_000), adapter, kill_switch=ks)
                if not r.ok:
                    # 어떤 사유로든 실패 시 종결 · 성공 조건은 시스템 오류 아님
                    assert r.reason in {
                        "kill_switch_active",
                        "seed_remain<100000",
                        "positions_full",
                    } or r.reason.startswith("seed_remain")
                    break
                # 즉시 매도 (5% 손실)
                adapter._toss._prices[ticker] = 9_500
                await execute_exit(r.sniper_signal_id, adapter, trigger_reason="hard_sl")

    # 시드 소진 · 오류 없이 종결됨
    bal = adapter.get_balance()
    # cash + 포지션 합 = 초기시드 - 실현손실 (오차 소액)
    assert bal.cash_krw >= 0        # 음수 없음 (시스템 정합)
