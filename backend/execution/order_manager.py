"""OMI (Order Manager Interface) — v2 트랙 C Phase 1.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §5

모든 브로커 어댑터(PaperAdapter · TossAdapter)가 준수해야 하는 계약.
시그널 엔진과 SignalRouter 는 이 인터페이스만 참조하며,
어떤 어댑터가 뒤에 연결되었는지 알 필요 없다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import (
    Balance,
    BrokerKind,
    MarketInfo,
    OrderRequest,
    OrderResult,
    Position,
)


class OrderManager(ABC):
    """Broker Adapter 공통 계약."""

    broker_kind: BrokerKind

    # ─── 주문 실행 ──────────────────────────────
    @abstractmethod
    def submit_order(self, req: OrderRequest) -> OrderResult:
        """주문 제출 (시장가/지정가 공통).

        - idempotency: 같은 `req.order_uuid` 로 재호출 시 이전 결과 반환.
        - Kill Switch 발동 상태이면 KillSwitchActive 예외.
        - 실패 시 exceptions.py 예외 계층 중 하나 raise.
        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """미체결 주문 취소. 이미 체결/취소된 경우 False 반환."""

    # ─── 조회 (부작용 없음 · 감사 로그 없음) ─────
    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """단일 주문 현재 상태 조회."""

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]:
        """단일 종목 포지션. 보유 0 이면 None."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """계좌 잔고 스냅샷 (현금 + 전 포지션 평가 · KRW·USD 통합)."""

    @abstractmethod
    def get_market_info(self, ticker: str) -> MarketInfo:
        """시장 상태 + 최근가 조회."""

    # ─── 라이프사이클 ──────────────────────────
    @abstractmethod
    def health_check(self) -> bool:
        """어댑터 정상 여부. Access Token 재발급 등 부작용 허용."""
