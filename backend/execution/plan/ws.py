"""시세 저장소 · 계획서 2절 (웹소켓 1개) · 6-1 「웹소켓 최근 체결」.

[미구현 · 확인 못 함] 토스 웹소켓의 접속 주소 · 메시지 모양 · 구독 방식은 이 저장소 문서와 시험 자료에 없다.
추측으로 접속 코드를 쓰지 않았다. 지금은 PriceStore(최근 체결 저장 · 나이 계산)만 있고,
웹소켓이 값을 넣지 않으면 6-1 이 REST(GET /prices)로 읽는다(10초 넘으면 REST · 확인용 두 번째 값도 REST).
웹소켓 연결은 토스 명세 확인 뒤 `PlanWsClient.run` 을 채운다 (보고서 「안 함」).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from .pricing import D


@dataclass
class _Tick:
    price: Decimal
    at: float


class PriceStore:
    """종목별 최근 체결가와 받은 시각."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._d: dict[str, _Tick] = {}
        self._clock = clock

    def put(self, symbol: str, price) -> None:
        self._d[symbol] = _Tick(D(price), self._clock())

    def get(self, symbol: str) -> Optional[tuple[Decimal, float]]:
        """(가격, 나이 초) · 없으면 None."""
        t = self._d.get(symbol)
        return None if t is None else (t.price, self._clock() - t.at)

    def fresh(self, symbol: str, max_age: float = 10.0) -> Optional[Decimal]:
        got = self.get(symbol)
        if got is None or got[1] > max_age:
            return None
        return got[0]


class PlanWsClient:
    """웹소켓 자리 표시 · 아직 연결하지 않는다 (위 설명)."""

    status = "none"   # 하트비트에 적는 값: none | connected | down

    def __init__(self, store: PriceStore):
        self.store = store

    async def run(self) -> None:  # pragma: no cover
        raise NotImplementedError("토스 웹소켓 명세 확인 전 · 구현하지 않음")
