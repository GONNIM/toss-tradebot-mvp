"""1025-02 · 손실 자동 정지 (하루 실현 손익 → Kill Switch) 수리 시험.

계획: docs/plans/site-roadmap/a1-daily-loss-stop.md
① 끝까지 흐름 -3% 발동 ② 이익만 미발동 ③ 부분 체결 ④ 수수료 ⑤ 감사 행 없음 → 계산 불가 · 알림 하루 1회
⑥ REJECTED 청산 ⑦ 매도 수량 초과 ⑧ 어제 청산 제외 ⑨ risk_budget 조회 실패 → 차단 ⑩ 직접 경로 order_audit 기록
1105-02 · 자동 정지 뒤 보유 종목 같은 주기 청산
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch as mock_patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.live_tape import entry as entry_mod
from backend.discovery.live_tape import sniper as sniper_mod
from backend.discovery.live_tape.entry import execute_entry
from backend.discovery.live_tape.exit import execute_exit
from backend.discovery.live_tape.params import SniperParamsStore
from backend.execution import audit as audit_mod
from backend.execution import risk_budget as rb_mod
from backend.execution.audit import daily_pnl_detail, pair_pnl
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.kill_switch import KillSwitch
from backend.execution.models import Balance, BrokerKind, OrderRequest, OrderSide, OrderType
from backend.services.db import get_session, init_db
from backend.services.models import OrderAudit, SniperSignal

from .test_sniper import _pass_warnings, make_candidate

UTC = timezone.utc


def _today0() -> datetime:
    return datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def store(tmp_path):
    s = SniperParamsStore(path=tmp_path / "sniper_params.json")
    s.patch({"per_order_krw": 100_000, "max_concurrent_positions": 1, "daily_loss_limit_pct": -0.03})
    return s


@pytest.fixture
def paper(tmp_path):
    from .conftest import SniperFakeTossClient
    ks = KillSwitch(state_path=tmp_path / "ks.json", notifier=None)
    fake = SniperFakeTossClient(prices={})
    adapter = PaperAdapter(state_path=tmp_path / "paper.json", kill_switch=ks, toss_client=fake)
    adapter.reset(cash_krw=1_000_000)
    return adapter, ks


@pytest.fixture
def wired(monkeypatch, store, paper):
    """sniper 모듈의 전역 Kill Switch · params 를 시험 인스턴스로 (Fable 1025-02-02 권고 1)."""
    adapter, ks = paper
    monkeypatch.setattr(entry_mod, "get_sniper_params", lambda: store.get())
    monkeypatch.setattr(sniper_mod, "get_sniper_params", lambda: store.get())
    monkeypatch.setattr(sniper_mod, "get_kill_switch", lambda: ks)
    monkeypatch.setenv("EXECUTION_BROKER", "paper")
    sniper_mod._daily_once.clear()
    return adapter, ks


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


async def _round_trip(adapter, ks, ticker: str, buy: float, sell: float):
    adapter._toss._prices[ticker] = buy
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r = await execute_entry(make_candidate(ticker, buy), adapter, kill_switch=ks)
    assert r.ok, r.reason
    adapter._toss._prices[ticker] = sell
    x = await execute_exit(r.sniper_signal_id, adapter, trigger_reason="hard_sl")
    assert x.ok, x.reason
    return r, x


def _audit(uuid, side, status="filled", qty=10, price=10_000.0, fee=0.0, created_at=None):
    return OrderAudit(
        order_uuid=uuid, broker_kind="paper", ticker="000001", side=side, order_type="market",
        qty=qty, status=status, filled_qty=qty if status in {"filled", "partial"} else 0,
        avg_fill_price=price if status in {"filled", "partial"} else None, total_fee=fee,
        created_at=created_at,
    )


# ① 끝까지 흐름 · 시드 100만 · 주문 10만 · 5% 하락 → 왕복 1회 약 -5,029원 · 6회째 -3% 넘어 발동
async def test_loss_rounds_trigger_kill_switch(db_ready, wired):
    adapter, ks = wired
    for i in range(1, 6):
        await _round_trip(adapter, ks, f"{i:06d}", 10_000, 9_500)
        assert await sniper_mod.check_daily_loss_and_trigger_ks() is None
        assert ks.is_active() is False
    await _round_trip(adapter, ks, "000006", 10_000, 9_500)
    out = await sniper_mod.check_daily_loss_and_trigger_ks()
    assert out and out["triggered"] is True
    assert out["realized_pct"] <= -0.03
    assert ks.is_active() is True
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 6 and d.uncomputable == []
    assert -30_300 < d.realized_krw < -30_000


# ② 이익만이면 발동하지 않음 · 손익은 양수
async def test_profit_only_no_trigger(db_ready, wired):
    adapter, ks = wired
    for i in range(1, 4):
        await _round_trip(adapter, ks, f"{i:06d}", 10_000, 10_500)
    assert await sniper_mod.check_daily_loss_and_trigger_ks() is None
    assert ks.is_active() is False
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.realized_krw > 0 and d.computed == 3


# ③ 부분 체결 · q = min(매도, 매수) · 수수료는 수량 비례
def test_pair_partial_fill():
    buy = _audit("b", "buy", qty=10, price=10_000, fee=10)
    sell = _audit("s", "sell", status="partial", qty=5, price=9_000, fee=5)
    pnl, why = pair_pnl(buy, sell)
    assert why is None
    assert pnl == pytest.approx(9_000 * 5 - 5 - (10_000 * 5 + 10 * 5 / 10))


# ④ 수수료가 손익에서 빠짐
def test_pair_fees_reduce_pnl():
    buy = _audit("b", "buy", price=10_000, fee=15)
    sell = _audit("s", "sell", price=10_000, fee=14)
    pnl, _ = pair_pnl(buy, sell)
    assert pnl == pytest.approx(-29)


# ⑤ 감사 행이 없는 오늘 청산 → 계산 불가 · 알림은 같은 signal 하루 1회
async def test_missing_audit_uncomputable_alert_once(db_ready, wired, monkeypatch):
    sent = []

    class _FakeNotifier:
        async def send_warning(self, title, body, category=None, dedupe_id=None):
            sent.append(title)
            return True

    import backend.services.notifier as notifier_mod
    monkeypatch.setattr(notifier_mod, "TelegramNotifier", _FakeNotifier)
    async with get_session() as session:
        session.add(SniperSignal(ticker="000009", entry_order_uuid="nobuy", entry_price=10_000,
                                 exit_order_uuid="nosell", exit_price=9_000))
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 0 and len(d.uncomputable) == 1
    assert d.uncomputable[0][1] == "buy_audit_missing"
    await sniper_mod.check_daily_loss_and_trigger_ks()
    await sniper_mod.check_daily_loss_and_trigger_ks()
    assert sent == ["하루 손익 계산 불가"]


async def _seed_pair(buy: OrderAudit, sell: OrderAudit):
    async with get_session() as session:
        session.add(buy)
        session.add(sell)
        session.add(SniperSignal(ticker="000001", entry_order_uuid=buy.order_uuid, entry_price=10_000,
                                 exit_order_uuid=sell.order_uuid, exit_price=9_000))


# ⑥ 매도 주문이 거부(REJECTED)되었는데 exit_order_uuid 가 채워진 경우 → 계산 불가
async def test_rejected_exit_uncomputable(db_ready):
    await _seed_pair(_audit("b6", "buy"), _audit("s6", "sell", status="rejected"))
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 0 and d.uncomputable[0][1] == "sell_status:rejected"


# ⑦ 매도 수량이 매수 수량보다 많음 (기존 보유 섞임) → 계산 불가
async def test_sell_qty_over_buy_uncomputable(db_ready):
    await _seed_pair(_audit("b7", "buy", qty=10), _audit("s7", "sell", qty=15, price=9_000))
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 0 and d.uncomputable[0][1].startswith("sell_qty>")


# ⑧ 어제 청산은 제외 · 오늘 청산만 (created_at 은 naive UTC 로 명시 · Fable 권고 5)
async def test_yesterday_exit_excluded(db_ready):
    y = (_today0() - timedelta(hours=1)).replace(tzinfo=None)
    t = (_today0() + timedelta(hours=1)).replace(tzinfo=None)
    await _seed_pair(_audit("b8y", "buy", created_at=y), _audit("s8y", "sell", price=5_000, created_at=y))
    await _seed_pair(_audit("b8t", "buy", created_at=t), _audit("s8t", "sell", price=9_000, created_at=t))
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 1
    assert d.realized_krw == pytest.approx((9_000 - 10_000) * 10)


# ⑨ 매수 전 검사 (signal_router 경로) 는 손익 조회 실패 시 매수 차단
async def test_risk_budget_blocks_on_pnl_error(monkeypatch, tmp_path):
    from backend.execution.params import ExecutionParamsStore

    async def _boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(rb_mod, "daily_realized_pnl", _boom)
    checker = rb_mod.RiskBudgetChecker(params_store=ExecutionParamsStore(path=tmp_path / "exec.json"))
    req = OrderRequest(ticker="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1)
    bal = Balance(cash_krw=1_000_000, cash_usd=0, total_equity_krw=1_000_000)
    res = await checker.check(req, bal, BrokerKind.PAPER)
    assert res.passed is False and res.rule == "daily_loss_limit"


# ⑩ 직접 경로 (sniper entry · exit) 가 order_audit 에 매수·매도 행을 남김
async def test_direct_path_records_audit(db_ready, wired):
    adapter, ks = wired
    r, x = await _round_trip(adapter, ks, "000001", 10_000, 10_000)
    async with get_session() as session:
        rows = (await session.execute(select(OrderAudit))).scalars().all()
    sides = sorted(row.side for row in rows)
    assert sides == ["buy", "sell"]
    assert {row.order_uuid for row in rows} == {r.order_uuid, x.order_uuid}
    assert all(row.signal_source == "sniper" for row in rows)


# 기록 실패는 주문 흐름을 막지 않음
async def test_audit_failure_does_not_block(db_ready, wired, monkeypatch):
    adapter, ks = wired

    async def _boom(*a, **kw):
        raise RuntimeError("audit down")

    monkeypatch.setattr(audit_mod, "record_order_result", _boom)
    r, x = await _round_trip(adapter, ks, "000002", 10_000, 9_000)
    assert r.ok and x.ok


# 1105-02 · 끝까지 흐름: 손실 6회 → 자동 정지 (매도 허용) → 보유 1종목이 같은 5초 주기에서 청산 · 새 진입 거부
async def test_auto_stop_then_held_position_exits_same_cycle(db_ready, wired, store, monkeypatch):
    from types import SimpleNamespace

    adapter, ks = wired
    store.patch({"max_concurrent_positions": 2, "enabled": True})
    adapter._toss._prices["000007"] = 10_000
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            held = await execute_entry(make_candidate("000007", 10_000), adapter, kill_switch=ks)
    assert held.ok, held.reason
    for i in range(1, 7):
        await _round_trip(adapter, ks, f"{i:06d}", 10_000, 9_500)
    assert ks.is_active() is False

    async def _exit_now(signal_id):
        return SimpleNamespace(should_exit=True, reason="hard_sl")

    monkeypatch.setattr(sniper_mod, "_resolve_order_manager", lambda: adapter)
    monkeypatch.setattr(sniper_mod, "poll_trailing", _exit_now)
    adapter._toss._prices["000007"] = 9_800
    stats = await sniper_mod.manage_positions()
    assert ks.is_active() is True and ks.status().sell_allowed is True
    assert stats["open_positions"] == 1 and stats["exited"] == 1
    assert await sniper_mod.open_positions() == []
    # 새 진입은 거부
    adapter._toss._prices["000008"] = 10_000
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            r = await execute_entry(make_candidate("000008", 10_000), adapter, kill_switch=ks)
    assert r.ok is False and r.reason.startswith("kill_switch_active")
