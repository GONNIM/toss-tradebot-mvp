"""Sniper 테스트 공용 픽스처."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from backend.execution.brokers.toss_client import TossClient


class SniperFakeTossClient(TossClient):
    """Sniper 전용 · 실 HTTP 회피 · 시세만 stub."""

    def __init__(self, *, prices: Optional[dict[str, float]] = None):
        self._client_id = "fake"
        self._client_secret = "fake"
        self._account_seq = "1"
        self._token_cache_path = Path("/tmp/sniper_fake_toss.json")
        self._prices = prices or {}

    def access_token(self) -> str:
        return "fake"

    def buying_power(self, currency: str = "KRW") -> dict:
        return {"currency": currency, "cashBuyingPower": "0"}

    def holdings(self, symbol=None):
        return {"items": []}

    def prices(self, symbols):
        return [
            {"symbol": s, "price": str(self._prices[s])}
            for s in symbols if s in self._prices
        ]

    def set_price(self, ticker: str, price: float) -> None:
        self._prices[ticker] = price
