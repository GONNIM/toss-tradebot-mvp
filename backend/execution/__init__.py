"""Execution Layer — v2 트랙 C Phase 1.

시그널 엔진 → SignalRouter → OrderManager(ABC) → PaperAdapter / TossAdapter.
스펙: docs/plans/tradebot-mvp-v2/{01-track-c-roadmap.md, 02-omi-interface-spec.md}
"""
from __future__ import annotations

from .exceptions import (
    BrokerCommunicationError,
    DuplicateOrderError,
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    MarketClosed,
    OrderNotFound,
    OrderRejected,
    RateLimitExceeded,
    RiskBudgetViolation,
)
from .models import (
    Balance,
    BrokerKind,
    Fill,
    MarketInfo,
    MarketState,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from .order_manager import OrderManager

__all__ = [
    # ABC
    "OrderManager",
    # Enums
    "BrokerKind",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "MarketState",
    # Models
    "OrderRequest",
    "OrderResult",
    "Fill",
    "Position",
    "Balance",
    "MarketInfo",
    # Exceptions
    "ExecutionError",
    "OrderRejected",
    "InsufficientBalance",
    "MarketClosed",
    "RateLimitExceeded",
    "BrokerCommunicationError",
    "KillSwitchActive",
    "RiskBudgetViolation",
    "OrderNotFound",
    "DuplicateOrderError",
]
