"""OMI Contract Test 스위트 — PaperAdapter 검증.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §10

동일 스위트를 Phase 2 TossAdapter 에도 적용 (실 API 키 필요 · CI skip).
"""
from __future__ import annotations

import pytest

from backend.execution import (
    InsufficientBalance,
    KillSwitchActive,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)


TICKER_KR = "005930"        # 6자리 숫자 → KRW 통화 인식
TICKER_US = "WEN"           # 영문 → USD 통화 인식


def _buy_market(ticker: str = TICKER_KR, qty: int = 1) -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=qty,
        signal_source="meme_stock",
    )


def _buy_limit(ticker: str, price: float, qty: int = 1) -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=qty,
        price=price,
        signal_source="meme_stock",
    )


def _sell_market(ticker: str, qty: int = 1) -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        qty=qty,
        signal_source="meme_stock",
    )


# ═══════════════════════════════════════════════════════════════
async def test_submit_market_buy_and_fill(paper):
    req = _buy_market(TICKER_KR, qty=2)
    result = paper.submit_order(req)
    assert result.status == OrderStatus.FILLED
    assert result.filled_qty == 2
    assert result.remaining_qty == 0
    assert result.avg_fill_price == 100_000.0
    assert result.broker_order_id.startswith("paper-")
    assert len(result.fills) == 1
    assert result.fills[0].fee > 0


# ═══════════════════════════════════════════════════════════════
async def test_submit_limit_buy_pending(paper):
    # 시장가(100_000) 보다 훨씬 낮은 지정가 → 즉시 체결 실패 → PENDING(=ACCEPTED)
    req = _buy_limit(TICKER_KR, price=1.0, qty=1)
    result = paper.submit_order(req)
    assert result.status == OrderStatus.ACCEPTED
    assert result.remaining_qty == 1
    assert result.filled_qty == 0


# ═══════════════════════════════════════════════════════════════
async def test_duplicate_order_idempotency(paper):
    req = _buy_market(TICKER_KR, qty=1)
    r1 = paper.submit_order(req)
    # 같은 order_uuid 로 다시 제출 → idempotency cache hit
    r2 = paper.submit_order(req)
    assert r1.order_uuid == r2.order_uuid
    assert r2.status == OrderStatus.FILLED
    # 신규 주문 실행되지 않음 확인: cash 는 1회만 차감
    bal = paper.get_balance()
    # 1주 × 100,000 + 수수료 15원
    expected_cash = 10_000_000 - (100_000 + 100_000 * 0.00015)
    assert abs(bal.cash_krw - expected_cash) < 0.01


# ═══════════════════════════════════════════════════════════════
async def test_insufficient_balance(paper):
    # 잔고 (10M) 이상 매수 시도
    req = _buy_market(TICKER_KR, qty=200)
    with pytest.raises(InsufficientBalance) as exc_info:
        paper.submit_order(req)
    assert exc_info.value.code == "insufficient-cash"


# ═══════════════════════════════════════════════════════════════
async def test_cancel_pending_order(paper):
    req = _buy_limit(TICKER_KR, price=1.0, qty=1)
    r = paper.submit_order(req)
    assert r.status == OrderStatus.ACCEPTED
    ok = paper.cancel_order(r.broker_order_id)
    assert ok is True
    # 재취소는 False
    assert paper.cancel_order(r.broker_order_id) is False


# ═══════════════════════════════════════════════════════════════
async def test_cancel_filled_order_returns_false(paper):
    r = paper.submit_order(_buy_market(TICKER_KR, qty=1))
    assert r.status == OrderStatus.FILLED
    # FILLED 주문 취소 시도 → False
    assert paper.cancel_order(r.broker_order_id) is False


# ═══════════════════════════════════════════════════════════════
async def test_get_balance_returns_positions(paper):
    paper.submit_order(_buy_market(TICKER_KR, qty=3))
    bal = paper.get_balance()
    tickers = [p.ticker for p in bal.positions]
    assert TICKER_KR in tickers
    pos = next(p for p in bal.positions if p.ticker == TICKER_KR)
    assert pos.qty == 3
    assert pos.avg_price == 100_000.0
    assert pos.currency == "KRW"


# ═══════════════════════════════════════════════════════════════
async def test_market_closed_rejected(paper, fake_toss):
    # PaperAdapter 는 시장 시간 검증을 하지 않지만, 시세 없으면 ERROR 반환
    fake_toss.set_price("UNKNOWN", None)  # 명시적 미설정
    req = OrderRequest(
        ticker="UNKNOWN",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
        signal_source="meme_stock",
    )
    r = paper.submit_order(req)
    assert r.status == OrderStatus.ERROR
    assert r.error_code == "price-unavailable"


# ═══════════════════════════════════════════════════════════════
async def test_kill_switch_blocks_new_orders(paper, kill_switch):
    kill_switch.activate(reason="test", actor="auto:test")
    with pytest.raises(KillSwitchActive):
        paper.submit_order(_buy_market(TICKER_KR, qty=1))
    kill_switch.deactivate(actor="user:test")


# ═══════════════════════════════════════════════════════════════
async def test_health_check_ok(paper):
    assert paper.health_check() is True


# ═══════════════════════════════════════════════════════════════
# 추가: get_order_status
async def test_get_order_status_pending_and_filled(paper):
    lim = paper.submit_order(_buy_limit(TICKER_KR, price=1.0, qty=1))
    fetched = paper.get_order_status(lim.broker_order_id)
    assert fetched.status == OrderStatus.ACCEPTED

    filled = paper.submit_order(_buy_market(TICKER_KR, qty=1))
    got = paper.get_order_status(filled.broker_order_id)
    assert got.status == OrderStatus.FILLED
    assert got.filled_qty == 1


# ═══════════════════════════════════════════════════════════════
# 추가: sell path
async def test_sell_reduces_position(paper):
    paper.submit_order(_buy_market(TICKER_KR, qty=3))
    pre = paper.get_position(TICKER_KR)
    assert pre.qty == 3

    paper.submit_order(_sell_market(TICKER_KR, qty=2))
    post = paper.get_position(TICKER_KR)
    assert post.qty == 1

    paper.submit_order(_sell_market(TICKER_KR, qty=1))
    assert paper.get_position(TICKER_KR) is None


# ═══════════════════════════════════════════════════════════════
async def test_sell_without_holding_raises(paper):
    with pytest.raises(InsufficientBalance) as exc_info:
        paper.submit_order(_sell_market("UNKNOWN", qty=1))
    assert exc_info.value.code == "insufficient-position"
