"""TossAdapter Mock Contract Test — v2 트랙 C Phase 2.

httpx.MockTransport 대신 TossClient 자체를 Fake 로 대체 (경계 명확 · 의존 최소).
동일 Contract Test 스위트를 PaperAdapter/TossAdapter 양쪽 검증.

Toss 전용 시나리오:
- 401 invalid-token → 재발급 후 재시도 (구현부에서 raise)
- 422 insufficient-buying-power → InsufficientBalance
- 422 order-hours-closed → MarketClosed
- 422 idempotency-key-conflict → DuplicateOrderError
- 429 rate-limit-exceeded → RateLimitExceeded
- 하드 상한 초과 → InsufficientBalance (hard-cap-max-order-amount)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from backend.execution import (
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    MarketClosed,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from backend.execution.brokers.toss_adapter import TossAdapter, _make_client_order_id
from backend.execution.brokers.toss_client import TossEnvelope
from backend.execution.kill_switch import KillSwitch


# ═══════════════════════════════════════════════════════════════
# Fake TossClient
# ═══════════════════════════════════════════════════════════════
class FakeTossClient:
    """TossClient contract 를 구현하는 stub · 순차 응답 큐 지원."""

    def __init__(self):
        self._prices: dict[str, float] = {"005930": 100_000.0, "WEN": 50.0}
        self._holdings_items: list[dict] = []
        self._orders: dict[str, dict] = {}          # orderId → order dict
        self._create_responses: list[dict | Exception] = []  # 순차 응답
        self._calendar_responses: dict[str, dict] = {}
        self.request_counter = 0

    # ── Fake state 설정 ──
    def set_price(self, ticker: str, price: Optional[float]):
        if price is None:
            self._prices.pop(ticker, None)
        else:
            self._prices[ticker] = price

    def set_holdings(self, items: list[dict]):
        self._holdings_items = items

    def enqueue_create_response(self, resp: dict | Exception):
        self._create_responses.append(resp)

    def set_order(self, order_id: str, order: dict):
        self._orders[order_id] = order

    def set_calendar(self, market: str, result: dict):
        self._calendar_responses[market.upper()] = result

    # ── TossClient interface ──
    def access_token(self) -> str:
        return "fake-token"

    def buying_power(self, currency: str = "KRW") -> dict:
        return {"currency": currency, "cashBuyingPower": "10000000" if currency == "KRW" else "5000"}

    def holdings(self, symbol: Optional[str] = None) -> dict:
        items = self._holdings_items
        if symbol:
            items = [i for i in items if i.get("symbol") == symbol]
        return {
            "items": items,
            "marketValue": {"amount": {"krw": "0", "usd": "0"}},
        }

    def prices(self, symbols: list[str]):
        return [
            {"symbol": s, "price": str(self._prices[s])}
            for s in symbols
            if s in self._prices
        ]

    def get(self, path: str, *, params=None, use_account_header: bool = True):
        # 환율 요청 지원 (get_balance 내부)
        if path == "/api/v1/exchange-rate":
            return {"USD": 1370.0}
        return {}

    def create_order(self, body: dict) -> TossEnvelope:
        self.request_counter += 1
        if not self._create_responses:
            # 기본 응답: PENDING
            resp = {
                "orderId": f"toss-{self.request_counter:06d}",
                "status": "PENDING",
                "symbol": body.get("symbol"),
                "quantity": body.get("quantity"),
                "orderedAt": datetime.now(tz=timezone.utc).isoformat(),
            }
        else:
            resp = self._create_responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
        # store order for status queries
        self._orders[resp["orderId"]] = resp
        return TossEnvelope(result=resp, request_id=f"req-{self.request_counter}")

    def cancel_order(self, order_id: str) -> TossEnvelope:
        if order_id not in self._orders:
            from backend.execution.exceptions import OrderNotFound
            raise OrderNotFound(f"order-not-found: {order_id}")
        self._orders[order_id]["status"] = "CANCELED"
        return TossEnvelope(
            result={"orderId": order_id, "status": "CANCELED"},
            request_id=f"req-cancel-{order_id}",
        )

    def get_order(self, order_id: str) -> TossEnvelope:
        if order_id not in self._orders:
            from backend.execution.exceptions import OrderNotFound
            raise OrderNotFound(f"order-not-found: {order_id}")
        return TossEnvelope(
            result=self._orders[order_id],
            request_id=f"req-get-{order_id}",
        )

    def market_calendar(self, market: str) -> TossEnvelope:
        result = self._calendar_responses.get(market.upper()) or _default_open_calendar(market)
        return TossEnvelope(result=result, request_id=f"req-cal-{market}")


def _default_open_calendar(market: str) -> dict:
    """항상 정규장 open (테스트 편의)."""
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    start = (now - timedelta(hours=1)).isoformat()
    end = (now + timedelta(hours=6)).isoformat()
    reg = {"startTime": start, "endTime": end}
    if market.upper() == "KR":
        return {"today": {"integrated": {"regularMarket": reg}}}
    return {"today": {"regularMarket": reg}}


# ═══════════════════════════════════════════════════════════════
# 픽스처
# ═══════════════════════════════════════════════════════════════
@pytest.fixture
def fake_toss_v2():
    return FakeTossClient()


@pytest.fixture(autouse=True)
def _reset_calendar():
    """Market Calendar 싱글턴 초기화 (테스트 간 격리)."""
    import backend.execution.market_calendar as mc
    mc._calendar = None
    yield
    mc._calendar = None


@pytest.fixture
def toss_kill_switch(tmp_paths):
    return KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)


@pytest.fixture
def toss_adapter(fake_toss_v2, toss_kill_switch):
    # Market Calendar 도 Fake 로 교체
    import backend.execution.market_calendar as mc
    mc._calendar = mc.MarketCalendar(toss_client=fake_toss_v2)
    # 하드 상한 · 300만원 (테스트 편의)
    adapter = TossAdapter(
        toss_client=fake_toss_v2,
        kill_switch=toss_kill_switch,
        max_order_amount_krw=3_000_000,
    )
    return adapter


# ═══════════════════════════════════════════════════════════════
# Contract Tests
# ═══════════════════════════════════════════════════════════════
async def test_toss_submit_market_buy_pending(toss_adapter, fake_toss_v2):
    # Toss 는 즉시 filled 안 함 · 기본 PENDING (감사 로그에 orderId 기록)
    req = OrderRequest(
        ticker="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
        signal_source="meme_stock",
    )
    result = toss_adapter.submit_order(req)
    assert result.status == OrderStatus.ACCEPTED
    assert result.broker_order_id.startswith("toss-")
    assert result.raw_response["request_id"] == "req-1"


async def test_toss_submit_limit_buy_pending(toss_adapter):
    req = OrderRequest(
        ticker="005930",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        price=95_000.0,
        signal_source="meme_stock",
    )
    result = toss_adapter.submit_order(req)
    assert result.status == OrderStatus.ACCEPTED
    assert result.broker_order_id.startswith("toss-")


async def test_toss_duplicate_order_uuid_uses_server_status(toss_adapter, fake_toss_v2):
    req = OrderRequest(
        ticker="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
        signal_source="meme_stock",
    )
    r1 = toss_adapter.submit_order(req)
    assert fake_toss_v2.request_counter == 1

    # 같은 order_uuid 재제출 → 서버 조회 (create_order 재호출 없음)
    r2 = toss_adapter.submit_order(req)
    assert fake_toss_v2.request_counter == 1
    assert r1.broker_order_id == r2.broker_order_id


async def test_toss_market_closed_local_gating(fake_toss_v2, toss_kill_switch):
    # 캘린더를 CLOSED 로 설정
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    closed = {
        "startTime": (now - timedelta(hours=10)).isoformat(),
        "endTime": (now - timedelta(hours=5)).isoformat(),
    }
    fake_toss_v2.set_calendar("KR", {"today": {"integrated": {"regularMarket": closed}}})

    import backend.execution.market_calendar as mc
    mc._calendar = mc.MarketCalendar(toss_client=fake_toss_v2)
    adapter = TossAdapter(
        toss_client=fake_toss_v2,
        kill_switch=toss_kill_switch,
        max_order_amount_krw=3_000_000,
    )
    with pytest.raises(MarketClosed) as exc_info:
        adapter.submit_order(
            OrderRequest(
                ticker="005930",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=1,
                signal_source="meme_stock",
            )
        )
    assert exc_info.value.code == "local-market-closed"


async def test_toss_hard_cap_max_order_amount(toss_adapter):
    # 하드 상한 3M · 100주 × 100,000 = 10M 초과
    with pytest.raises(InsufficientBalance) as exc_info:
        toss_adapter.submit_order(
            OrderRequest(
                ticker="005930",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=100,
                signal_source="meme_stock",
            )
        )
    assert exc_info.value.code == "hard-cap-max-order-amount"


async def test_toss_kill_switch_blocks(toss_adapter, toss_kill_switch):
    toss_kill_switch.activate("test", "auto:test")
    with pytest.raises(KillSwitchActive):
        toss_adapter.submit_order(
            OrderRequest(
                ticker="005930",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=1,
                signal_source="meme_stock",
            )
        )
    toss_kill_switch.deactivate("user:test")


async def test_toss_insufficient_balance_maps(fake_toss_v2, toss_adapter):
    # create_order 응답으로 InsufficientBalance 유발
    from backend.execution.exceptions import InsufficientBalance
    fake_toss_v2.enqueue_create_response(
        InsufficientBalance("insufficient-buying-power", "잔고 부족")
    )
    with pytest.raises(InsufficientBalance):
        toss_adapter.submit_order(
            OrderRequest(
                ticker="005930",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=1,
                signal_source="meme_stock",
            )
        )


async def test_toss_cancel_pending(toss_adapter, fake_toss_v2):
    req = OrderRequest(
        ticker="005930",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        price=90_000,
        signal_source="meme_stock",
    )
    r = toss_adapter.submit_order(req)
    ok = toss_adapter.cancel_order(r.broker_order_id)
    assert ok is True


async def test_toss_cancel_unknown_returns_false(toss_adapter):
    assert toss_adapter.cancel_order("non-existent-orderId") is False


async def test_toss_get_order_status(toss_adapter):
    req = OrderRequest(
        ticker="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
        signal_source="meme_stock",
    )
    r = toss_adapter.submit_order(req)
    got = toss_adapter.get_order_status(r.broker_order_id)
    assert got.status == OrderStatus.ACCEPTED
    assert got.broker_order_id == r.broker_order_id


async def test_toss_get_position(toss_adapter, fake_toss_v2):
    fake_toss_v2.set_holdings(
        [
            {
                "symbol": "005930",
                "quantity": "5",
                "averagePurchasePrice": "70000",
                "lastPrice": "100000",
                "currency": "KRW",
            }
        ]
    )
    pos = toss_adapter.get_position("005930")
    assert pos is not None
    assert pos.qty == 5
    assert pos.avg_price == 70000.0
    assert pos.current_price == 100000.0


async def test_toss_get_balance_krw_only(toss_adapter, fake_toss_v2):
    fake_toss_v2.set_holdings([])
    bal = toss_adapter.get_balance()
    assert bal.cash_krw == 10_000_000.0
    assert bal.cash_usd == 5000.0


async def test_toss_health_check(toss_adapter):
    assert toss_adapter.health_check() is True


async def test_toss_client_order_id_regex():
    # UUID 다양한 형태 → 규칙 준수
    import uuid as _uuid
    for _ in range(20):
        u = str(_uuid.uuid4())
        coid = _make_client_order_id(u)
        assert 1 <= len(coid) <= 36
        assert all(c.isalnum() or c in "_-" for c in coid)
