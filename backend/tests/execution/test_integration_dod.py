"""Phase 1 DoD 통합 시나리오 — end-to-end 검증.

스펙: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §4-6

시나리오:
1. EXECUTION_ENABLED=false → 시그널 → Router 무영향 (기존 알림만)
2. EXECUTION_ENABLED=true → meme 시그널 → PaperAdapter FILLED → audit 완전 기록
3. Kill Switch active → 시그널 스킵 · audit 미기록
4. 리스크 예산 위반 → 시그널 차단 · audit REJECTED 기록
5. API 로 Kill Switch 발동/해제 후 Router 동작 반영
"""
from __future__ import annotations

import os

import pytest

from backend.execution.audit import list_recent_audits
from backend.execution.signal_router import SignalEvent, SignalRouter
from backend.execution.models import BrokerKind, OrderStatus


TICKER = "005930"


@pytest.fixture(autouse=True)
def _reset_env():
    yield
    for k in ["EXECUTION_ENABLED", "EXECUTION_BROKER", "EXECUTION_MAX_ORDER_AMOUNT"]:
        os.environ.pop(k, None)


# ═══════════════════════════════════════════════════════════════
async def test_dod_disabled_no_side_effects(paper, kill_switch):
    """DoD 1: EXECUTION_ENABLED=false — Router 완전 무영향, audit 기록 없음."""
    os.environ["EXECUTION_ENABLED"] = "false"
    router = SignalRouter(paper, kill_switch=kill_switch)
    pre_rows = await list_recent_audits(ticker=TICKER, limit=5)
    pre_count = len(pre_rows)

    result = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=80,
            source="meme_stock",
            signal_id="dod-1",
        )
    )
    assert result is None

    post_rows = await list_recent_audits(ticker=TICKER, limit=5)
    assert len(post_rows) == pre_count


# ═══════════════════════════════════════════════════════════════
async def test_dod_full_pipeline_meme_buy(paper, kill_switch):
    """DoD 2: meme_stock BUY → PaperAdapter FILLED → order_audit INSERT."""
    os.environ["EXECUTION_ENABLED"] = "true"
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "500000"
    router = SignalRouter(paper, kill_switch=kill_switch)

    result = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=80,
            source="meme_stock",
            signal_id="dod-2",
        )
    )
    assert result is not None
    assert result.status == OrderStatus.FILLED
    assert result.filled_qty >= 1

    # Audit 기록 완전성 검증
    rows = await list_recent_audits(signal_source="meme_stock", limit=10)
    matched = [r for r in rows if r.signal_id == "dod-2"]
    assert len(matched) == 1
    row = matched[0]
    assert row.status == OrderStatus.FILLED.value
    assert row.broker_kind == BrokerKind.PAPER.value
    assert row.filled_qty >= 1
    assert row.avg_fill_price == 100_000.0
    assert row.total_fee > 0


# ═══════════════════════════════════════════════════════════════
async def test_dod_kill_switch_blocks_signal(paper, kill_switch):
    """DoD 3: Kill Switch active → Router 스킵 · audit 미기록."""
    os.environ["EXECUTION_ENABLED"] = "true"
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "500000"

    kill_switch.activate(reason="dod-test", actor="auto:test")
    router = SignalRouter(paper, kill_switch=kill_switch)

    result = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=100,
            source="meme_stock",
            signal_id="dod-3-blocked",
        )
    )
    assert result is None

    rows = await list_recent_audits(signal_source="meme_stock", limit=10)
    assert not any(r.signal_id == "dod-3-blocked" for r in rows)
    kill_switch.deactivate("user:test")


# ═══════════════════════════════════════════════════════════════
async def test_dod_risk_budget_records_rejected(paper, kill_switch):
    """DoD 4: 리스크 예산 위반 → audit 에 REJECTED 기록 (추적성 확보)."""
    os.environ["EXECUTION_ENABLED"] = "true"
    # 잔고 훨씬 초과 · InsufficientBalance 유발
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "100000000"

    router = SignalRouter(paper, kill_switch=kill_switch)
    result = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=100,
            source="activist",
            signal_id="dod-4-rejected",
        )
    )
    assert result is not None
    assert result.status == OrderStatus.REJECTED

    rows = await list_recent_audits(signal_source="activist", limit=10)
    matched = [r for r in rows if r.signal_id == "dod-4-rejected"]
    assert len(matched) == 1
    assert matched[0].status == OrderStatus.REJECTED.value
    assert matched[0].error_code is not None


# ═══════════════════════════════════════════════════════════════
async def test_dod_api_toggle_kill_switch(paper, kill_switch):
    """DoD 5: Kill Switch 상태 전환 시 Router 즉시 반영 (파일 기반 hot check)."""
    os.environ["EXECUTION_ENABLED"] = "true"
    os.environ["EXECUTION_MAX_ORDER_AMOUNT"] = "500000"
    router = SignalRouter(paper, kill_switch=kill_switch)

    # 1) active 상태 → route None
    kill_switch.activate("api-toggle-test", actor="auto:api")
    r1 = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=80,
            source="meme_stock",
            signal_id="dod-5-a",
        )
    )
    assert r1 is None

    # 2) 해제 → route 성공
    kill_switch.deactivate("user:api")
    r2 = await router.route(
        SignalEvent(
            ticker=TICKER,
            action="buy",
            strength=80,
            source="meme_stock",
            signal_id="dod-5-b",
        )
    )
    assert r2 is not None
    assert r2.status == OrderStatus.FILLED
