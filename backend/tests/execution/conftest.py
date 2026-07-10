"""Execution Layer 테스트 픽스처."""
from __future__ import annotations

import os

# 테스트 전용 DB 격리 (import 시점에 설정 필수)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import tempfile
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio

from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.brokers.toss_client import TossClient
from backend.execution.kill_switch import KillSwitch
from backend.execution.models import MarketInfo, MarketState
from backend.services.db import init_db


class _FakeTossClient(TossClient):
    """실 HTTP 호출 없이 시세만 제공. 잔고·holdings 는 빈 응답."""

    def __init__(self, *, prices: Optional[dict[str, float]] = None):
        # 부모 __init__ 회피 — env 조회 없이 stub
        self._client_id = "fake"
        self._client_secret = "fake"
        self._account_seq = "1"
        self._token_cache_path = Path("/tmp/fake_toss_token.json")
        self._prices = prices or {}

    def access_token(self) -> str:  # noqa: D401
        return "fake-token"

    def buying_power(self, currency: str = "KRW") -> dict:
        return {"currency": currency, "cashBuyingPower": "0"}

    def holdings(self, symbol=None):
        return {"items": []}

    def prices(self, symbols):
        result = []
        for s in symbols:
            price = self._prices.get(s)
            if price is not None:
                result.append({"symbol": s, "price": str(price)})
        return result

    def set_price(self, ticker: str, price: float) -> None:
        self._prices[ticker] = price


@pytest.fixture
def fake_toss():
    """PaperAdapter 가 실 Toss API 대신 사용할 stub."""
    return _FakeTossClient(prices={"005930": 100_000.0, "WEN": 50.0})


@pytest.fixture
def tmp_paths(tmp_path):
    """테스트별 격리된 상태 파일 경로."""
    return {
        "balance": tmp_path / "paper_balance.json",
        "kill_switch": tmp_path / "kill_switch.json",
        "params": tmp_path / "execution_params.json",
    }


@pytest.fixture
def kill_switch(tmp_paths):
    return KillSwitch(state_path=tmp_paths["kill_switch"], notifier=None)


@pytest_asyncio.fixture
async def db_ready():
    await init_db()
    yield


@pytest_asyncio.fixture
async def paper(db_ready, fake_toss, kill_switch, tmp_paths):
    """PaperAdapter · 10M KRW 초기 자본 · fake 시세."""
    adapter = PaperAdapter(
        toss_client=fake_toss,
        kill_switch=kill_switch,
        state_path=tmp_paths["balance"],
    )
    adapter.reset(cash_krw=10_000_000)
    return adapter
