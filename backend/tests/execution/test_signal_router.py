"""SignalRouter 스위트 — v2 트랙 C Phase 1."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.tests.execution.conftest import cleanup_principles, seed_principles_pass
from backend.execution.audit import list_recent_audits
from backend.execution.risk_budget import RiskBudgetChecker
from backend.execution.signal_router import SignalEvent, SignalRouter
from backend.execution.models import BrokerKind, OrderStatus


TICKER = "005930"


@pytest_asyncio.fixture(autouse=True)
async def _principles_pass(db_ready):
    """meme_stock 소스는 원칙 관문(principles_gate)을 거치므로 테스트 DB 에 PASS 행을 시딩."""
    run_id = await seed_principles_pass(TICKER)
    yield
    await cleanup_principles(run_id)


@pytest.fixture(autouse=True)
def _reset_env():
    os.environ["EXECUTION_ENABLED"] = "true"
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "500000"
    yield
    os.environ.pop("EXECUTION_ENABLED", None)
    os.environ.pop("EXECUTION_MAX_ORDER_AMOUNT", None)


async def test_router_skips_when_disabled(paper, kill_switch):
    os.environ["EXECUTION_ENABLED"] = "false"
    r = SignalRouter(paper, kill_switch=kill_switch)
    assert r.enabled() is False
    result = await r.route(
        SignalEvent(ticker=TICKER, action="buy", strength=80, source="meme_stock", signal_id="s1")
    )
    assert result is None


async def test_router_skips_when_kill_switch_active(paper, kill_switch):
    kill_switch.activate("test", "auto:test")
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker=TICKER, action="buy", strength=80, source="meme_stock", signal_id="s2")
    )
    assert result is None
    kill_switch.deactivate("user:test")


async def test_router_skips_hold_action(paper, kill_switch):
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker=TICKER, action="hold", strength=50, source="meme_stock", signal_id="s3")
    )
    assert result is None


async def test_router_maps_strength_to_qty(paper, kill_switch):
    # max_order 500,000 · strength=80% · price=100_000 → qty = 4
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker=TICKER, action="buy", strength=80, source="meme_stock", signal_id="s4")
    )
    assert result is not None
    assert result.status == OrderStatus.FILLED
    assert result.filled_qty == 4


async def test_router_records_audit(paper, kill_switch, db_ready):
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker=TICKER, action="buy", strength=50, source="activist", signal_id="audit-1")
    )
    assert result is not None
    rows = await list_recent_audits(signal_source="activist", limit=5)
    assert any(row.signal_id == "audit-1" for row in rows)


async def test_router_records_insufficient_as_rejected(paper, kill_switch, db_ready):
    # 잔고 훨씬 초과 시나리오
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "100000000"  # 1억
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker=TICKER, action="buy", strength=100, source="meme_stock", signal_id="rej-1")
    )
    assert result is not None
    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "insufficient-cash"


async def test_router_rejects_ticker_not_in_principles_pass(paper, kill_switch, db_ready):
    """meme_stock 소스라도 원칙 PASS 목록에 없는 종목은 관문에서 거절."""
    r = SignalRouter(paper, kill_switch=kill_switch)
    result = await r.route(
        SignalEvent(ticker="WEN", action="buy", strength=80, source="meme_stock", signal_id="gate-1")
    )
    assert result is not None
    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "principles-principles_fail_closed"
    rows = await list_recent_audits(ticker="WEN", limit=5)
    assert any(
        row.signal_id == "gate-1" and row.error_code == "principles-principles_fail_closed"
        for row in rows
    )
