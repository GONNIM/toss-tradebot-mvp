"""Execution Layer 예외 계층 — v2 트랙 C Phase 1.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §4
정규화 규칙: 어댑터는 브로커 원본 예외를 반드시 이 계층 중 하나로 감싸야 함.
"""
from __future__ import annotations

from typing import Optional


class ExecutionError(Exception):
    """OMI 최상위 예외."""

    def __init__(self, message: str = "", *, raw_response: Optional[dict] = None):
        super().__init__(message)
        self.raw_response = raw_response


class OrderRejected(ExecutionError):
    """브로커가 명시적으로 거부한 주문 (사유 있음)."""

    def __init__(self, code: str, message: str, *, raw_response: Optional[dict] = None):
        super().__init__(f"[{code}] {message}", raw_response=raw_response)
        self.code = code
        self.message = message


class InsufficientBalance(OrderRejected):
    """잔고 부족 (매수) 또는 수량 부족 (매도)."""


class MarketClosed(OrderRejected):
    """시장 외 시간 주문 시도."""


class RateLimitExceeded(ExecutionError):
    """브로커 API rate limit. 재시도 정책 적용 대상."""

    def __init__(self, retry_after: Optional[float] = None, message: str = "rate limit"):
        super().__init__(message)
        self.retry_after = retry_after


class BrokerCommunicationError(ExecutionError):
    """네트워크·타임아웃·5xx. 재시도 대상."""


class KillSwitchActive(ExecutionError):
    """Kill Switch 발동 상태에서 신규 주문 시도."""

    def __init__(self, reason: str = "kill switch active"):
        super().__init__(reason)
        self.reason = reason


class RiskBudgetViolation(ExecutionError):
    """리스크 예산 룰 위반 (종목당 상한·일일 손실 캡 등)."""

    def __init__(self, rule: str, detail: str = ""):
        super().__init__(f"[{rule}] {detail}")
        self.rule = rule
        self.detail = detail


class OrderNotFound(ExecutionError):
    """존재하지 않는 order_uuid / broker_order_id 조회 시도."""


class DuplicateOrderError(ExecutionError):
    """동일 order_uuid 중복 제출 (idempotency 위반)."""
