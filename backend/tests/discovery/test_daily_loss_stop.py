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


@pytest.fixture
def no_pre_check(monkeypatch):
    """매수 전 하루 손익 검사 (1105-04 방어 7 · 한도 70% 에서 멈춤) 를 끔.

    자동 정지 (-3%) 까지 손실 왕복을 쌓는 시험용 · 방어 7 은 따로 시험한다.
    """
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(entry_mod, "pre_entry_loss_block", _none)


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
async def test_loss_rounds_trigger_kill_switch(db_ready, wired, no_pre_check):
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
    assert sent == ["하루 손익 계산 불가 · 오늘 새 매수 멈춤"]


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

    monkeypatch.setattr(audit_mod, "daily_pnl_detail", _boom)
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
async def test_auto_stop_then_held_position_exits_same_cycle(db_ready, wired, store, monkeypatch, no_pre_check):
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


# ─── 1105-03 · 청산은 봇이 산 수량까지만 ───
def _manual_buy(adapter, ticker: str, qty: int, price: float):
    """사용자가 직접 산 주식 흉내 (감사 기록·신호 없이 어댑터에 바로 매수)."""
    adapter._toss._prices[ticker] = price
    r = adapter.submit_order(OrderRequest(ticker=ticker, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=qty))
    assert r.filled_qty == qty


async def _held(adapter, ticker: str) -> int:
    pos = adapter.get_position(ticker)
    return pos.qty if pos else 0


async def test_exit_sells_only_bot_qty_keeps_manual_shares(db_ready, wired, store):
    adapter, ks = wired
    store.patch({"max_concurrent_positions": 2})                       # 직접 산 종목도 보유 칸 1개를 씀
    _manual_buy(adapter, "000001", 20, 10_000)
    r, x = await _round_trip(adapter, ks, "000001", 10_000, 9_500)   # 봇 10주 매수 → 청산
    assert x.filled_qty == 10
    assert await _held(adapter, "000001") == 20                       # 직접 산 20주는 남음


async def _seed_signal(ticker: str, entry_uuid: str, entry_price: float = 10_000) -> int:
    async with get_session() as session:
        row = SniperSignal(ticker=ticker, entry_order_uuid=entry_uuid, entry_price=entry_price)
        session.add(row)
        await session.flush()
        return row.id


async def test_exit_canceled_entry_sells_nothing_and_closes(db_ready, wired):
    from backend.discovery.live_tape.trailing_stop import open_positions

    adapter, ks = wired
    _manual_buy(adapter, "000002", 5, 10_000)
    async with get_session() as session:
        session.add(_audit("e-can", "buy", status="canceled", qty=10))
    sid = await _seed_signal("000002", "e-can")
    x = await execute_exit(sid, adapter, trigger_reason="hard_sl")
    assert x.ok is False and x.reason == "entry_unfilled"
    assert await _held(adapter, "000002") == 5                        # 사용자 주식 안 팜
    assert sid not in await open_positions()                          # 5초마다 다시 시도하지 않음


async def test_exit_accepted_entry_uses_order_qty(db_ready, wired):
    adapter, ks = wired
    _manual_buy(adapter, "000003", 8, 10_000)
    async with get_session() as session:
        session.add(_audit("e-acc", "buy", status="accepted", qty=3))
    sid = await _seed_signal("000003", "e-acc")
    x = await execute_exit(sid, adapter, trigger_reason="hard_sl")
    assert x.ok and x.filled_qty == 3
    assert await _held(adapter, "000003") == 5


async def test_exit_without_audit_uses_approx_and_alerts_once(db_ready, wired, monkeypatch, store):
    from backend.discovery.live_tape import exit as exit_mod

    sent = []

    class _FakeNotifier:
        async def send_warning(self, title, body, category=None, dedupe_id=None):
            sent.append(title)
            return True

    import backend.services.notifier as notifier_mod
    monkeypatch.setattr(notifier_mod, "TelegramNotifier", _FakeNotifier)
    monkeypatch.setattr(exit_mod, "get_sniper_params", lambda: store.get())
    exit_mod._approx_alerted.clear()
    adapter, ks = wired
    _manual_buy(adapter, "000004", 30, 10_000)
    sid = await _seed_signal("000004", "no-audit", entry_price=10_000)   # 근사 100,000 ÷ 10,000 = 10주
    x = await execute_exit(sid, adapter, trigger_reason="hard_sl")
    assert x.ok and x.filled_qty == 10
    assert await _held(adapter, "000004") == 20
    assert sent == ["청산 수량 짐작"]


async def test_same_ticker_two_signals_exit_once_per_cycle(db_ready, wired, store, monkeypatch):
    from types import SimpleNamespace

    adapter, ks = wired
    store.patch({"enabled": True})
    _manual_buy(adapter, "000005", 20, 10_000)
    async with get_session() as session:
        session.add(_audit("e-a", "buy", qty=5))
        session.add(_audit("e-b", "buy", qty=5))
    await _seed_signal("000005", "e-a")
    await _seed_signal("000005", "e-b")

    async def _exit_now(signal_id):
        return SimpleNamespace(should_exit=True, reason="hard_sl")

    monkeypatch.setattr(sniper_mod, "_resolve_order_manager", lambda: adapter)
    monkeypatch.setattr(sniper_mod, "poll_trailing", _exit_now)
    stats = await sniper_mod.manage_positions()
    assert stats["exited"] == 1 and stats.get("deferred_same_ticker") == 1
    assert await _held(adapter, "000005") == 15
    stats2 = await sniper_mod.manage_positions()                      # 다음 주기에 두 번째
    assert stats2["exited"] == 1
    assert await _held(adapter, "000005") == 10


# ─── 1105-04 · 실주문 전 결정 ───
async def _enter(adapter, ks, ticker: str, price: float = 10_000):
    adapter._toss._prices[ticker] = price
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            return await execute_entry(make_candidate(ticker, price), adapter, kill_switch=ks)


# ㉤ 방어 7 · 실현 손실이 시드의 -2.1% (한도 -3% × 0.7) 에 닿으면 새 진입 거부 · 그 전에는 통과
async def test_pre_entry_blocks_at_70pct_of_limit(db_ready, wired, store):
    adapter, ks = wired
    for i in range(1, 6):                       # 4회 뒤 약 -2.01% → 5회째 진입 통과 · 5회 뒤 약 -2.51%
        await _round_trip(adapter, ks, f"{i:06d}", 10_000, 9_500)
    r6 = await _enter(adapter, ks, "000006")
    assert r6.ok is False and r6.reason.startswith("daily_loss_near_limit"), r6.reason
    assert ks.is_active() is False              # 자동 정지 (-3%) 는 아직


# ㉠ 오늘 손익을 계산 못 한 청산이 있으면 새 진입 거부 (계산 불가 사유 · 하루 내내)
async def test_uncomputable_today_blocks_entry(db_ready, wired):
    adapter, ks = wired
    t = (_today0() + timedelta(minutes=1)).replace(tzinfo=None)
    await _seed_pair(_audit("b-x", "buy", created_at=t), _audit("s-x", "sell", status="rejected", created_at=t))
    r = await _enter(adapter, ks, "000009")
    assert r.ok is False and r.reason.startswith("pnl_uncomputable_today(1)")


# ㉠ 체결 확인 중 (접수 · 체결 0) 인 청산은 계산 불가로 세지 않음 → 진입 막지 않음 · pending 으로 나뉨
async def test_pending_exit_does_not_block_entry(db_ready, wired):
    adapter, ks = wired
    t = (_today0() + timedelta(minutes=1)).replace(tzinfo=None)
    await _seed_pair(_audit("b-p", "buy", created_at=t), _audit("s-p", "sell", status="accepted", created_at=t))
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.uncomputable == [] and len(d.pending) == 1 and d.pending[0][1] == "pending:sell_accepted"
    r = await _enter(adapter, ks, "000010")
    assert r.ok, r.reason


# ㉤ 신호 연결 매수 전 검사도 분모는 시드 (총자산 1,000만이어도 시드 100만 기준 -2.5% → 막음)
async def test_risk_budget_uses_seed_denominator(db_ready, monkeypatch, tmp_path, store):
    from backend.discovery.live_tape import params as sp_mod
    from backend.execution.params import ExecutionParamsStore

    monkeypatch.setattr(sp_mod, "get_sniper_params", lambda: store.get())
    t = (_today0() + timedelta(minutes=1)).replace(tzinfo=None)
    await _seed_pair(_audit("b-r", "buy", created_at=t), _audit("s-r", "sell", price=7_500, created_at=t))  # -25,000
    checker = rb_mod.RiskBudgetChecker(params_store=ExecutionParamsStore(path=tmp_path / "exec.json"))
    req = OrderRequest(ticker="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1)
    bal = Balance(cash_krw=10_000_000, cash_usd=0, total_equity_krw=10_000_000)
    res = await checker.check(req, bal, BrokerKind.PAPER)
    assert res.passed is False and res.rule == "daily_loss_limit" and "daily_loss_near_limit" in res.detail


# ㉣ 신호 연결 매도 수량 = min(보유, 신호 연결이 산 순수량)
def _router_audit(uuid, side, source, qty, status="filled", ticker="000020"):
    return OrderAudit(
        order_uuid=uuid, broker_kind="paper", ticker=ticker, side=side, order_type="market",
        qty=qty, status=status, filled_qty=qty if status == "filled" else 0,
        avg_fill_price=10_000.0 if status == "filled" else None, signal_source=source,
    )


async def _route_vip_sell(adapter, ks, monkeypatch, ticker="000020"):
    from backend.execution.signal_router import SignalEvent, SignalRouter

    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    adapter._toss._prices[ticker] = 10_000
    router = SignalRouter(adapter, kill_switch=ks)
    return await router.route(SignalEvent(ticker=ticker, action="sell", strength=100, source="vip", signal_id="vip-sell-1"))


async def test_router_sell_skips_shares_bought_by_watchlist(db_ready, wired, monkeypatch):
    """관심 종목으로 산 주식에 유명 투자자 매도 신호 → 팔지 않음 (Fable 1105-04-01 막음 2)."""
    adapter, ks = wired
    _manual_buy(adapter, "000020", 8, 10_000)
    async with get_session() as session:
        session.add(_router_audit("w-buy", "buy", "watchlist", 8))
    assert await _route_vip_sell(adapter, ks, monkeypatch) is None
    assert await _held(adapter, "000020") == 8


async def test_router_sell_caps_to_router_net_qty(db_ready, wired, monkeypatch):
    """신호 연결이 5주 사고 3주 팖 · 열린 매도 1주 · 실계좌 행은 안 셈 → 순 1주 · 보유 8주 중 1주만 팖."""
    adapter, ks = wired
    _manual_buy(adapter, "000020", 8, 10_000)
    async with get_session() as session:
        session.add(_router_audit("v-buy", "buy", "vip", 5))
        session.add(_router_audit("v-sell", "sell", "meme_stock", 3))
        session.add(_router_audit("v-sell-open", "sell", "vip", 1, status="accepted"))
        session.add(OrderAudit(order_uuid="toss-buy", broker_kind="toss", ticker="000020", side="buy",
                               order_type="market", qty=9, status="filled", filled_qty=9, signal_source="vip"))
    res = await _route_vip_sell(adapter, ks, monkeypatch)
    assert res is not None and res.filled_qty == 1
    assert await _held(adapter, "000020") == 7


# ─── 1105-05 · 작은 고칠 점 ───
# 6 · 청산하면 청산 시각 (exited_at) 이 채워짐 · 7 · 하루 손익은 청산 시각이 오늘 이전인 행을 읽지 않음
async def test_exit_sets_exited_at_and_old_rows_skipped(db_ready, wired):
    adapter, ks = wired
    r, x = await _round_trip(adapter, ks, "000030", 10_000, 9_000)
    async with get_session() as session:
        row = await session.get(SniperSignal, r.sniper_signal_id)
        assert row.exited_at is not None
        row.exited_at = (_today0() - timedelta(days=1)).replace(tzinfo=None)   # 어제 청산으로 바꿈
    d = await daily_pnl_detail(BrokerKind.PAPER, _today0())
    assert d.computed == 0 and d.uncomputable == []


# 8 · 진입 출처가 주문 기록에 남음 (관심 종목 · 수동)
async def test_entry_source_recorded(db_ready, wired, store):
    adapter, ks = wired
    store.patch({"max_concurrent_positions": 3})
    adapter._toss._prices["000031"] = 10_000
    adapter._toss._prices["000032"] = 10_000
    with mock_patch.object(entry_mod, "_is_in_active_window", return_value=True):
        with mock_patch("backend.discovery.live_tape.entry.check_warnings", new=_pass_warnings):
            w = await execute_entry(make_candidate("000031", 10_000), adapter, kill_switch=ks, source="watchlist")
            m = await execute_entry(make_candidate("000032", 10_000), adapter, kill_switch=ks, source="manual")
    assert w.ok and m.ok
    async with get_session() as session:
        assert (await session.get(OrderAudit, w.order_uuid)).signal_source == "watchlist"
        assert (await session.get(OrderAudit, m.order_uuid)).signal_source == "manual"


# 9 · 체결 수수료 · 응답 칸이 있으면 그 값 · 없으면 수수료율 짐작 (표식 rate_estimate)
def test_reconciler_fee_source():
    from backend.execution.reconciler import _fee_of

    assert _fee_of({}, {"commission": "15"}, "005930", 10, 10_000.0) == (15.0, "toss_response")
    fee, src = _fee_of({}, {}, "005930", 10, 10_000.0)
    assert src == "rate_estimate" and fee == pytest.approx(100_000 * 0.00015)
    fee, src = _fee_of({}, {}, "AAPL", 2, 100.0)
    assert src == "rate_estimate" and fee == pytest.approx(200 * 0.0025)
    assert _fee_of({}, {}, "005930", 0, None) == (0.0, "none")
