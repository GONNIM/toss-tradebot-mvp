"""Execution Layer 데이터 모델 — v2 트랙 C Phase 1.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §2-§3
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


class BrokerKind(str, Enum):
    PAPER = "paper"
    TOSS = "toss"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    """OMI 표준 상태 — 어댑터가 브로커별 상태를 이 값으로 정규화."""
    PENDING = "pending"          # 접수 대기 (idempotency 큐)
    ACCEPTED = "accepted"        # 브로커 접수 완료
    PARTIAL_FILL = "partial"     # 부분 체결
    FILLED = "filled"            # 전량 체결
    CANCELED = "canceled"        # 취소됨
    REJECTED = "rejected"        # 브로커 거부
    ERROR = "error"              # 시스템 에러
    KILLED = "killed"            # Kill Switch 발동으로 차단


class MarketState(str, Enum):
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    HALT = "halt"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class OrderRequest:
    """시그널 엔진 → Signal Router → OrderManager 입력."""
    ticker: str
    side: OrderSide
    order_type: OrderType
    qty: int                             # 정수 주식 수. Toss는 decimal string 이지만 OMI는 정수 표준.
    price: Optional[float] = None        # LIMIT 필수 · MARKET 무시
    # === 메타 ===
    order_uuid: str = field(default_factory=lambda: str(uuid4()))
    signal_source: str = "unknown"       # meme_stock | vip | activist | sector_leaders | super_signal
    signal_id: Optional[str] = None      # 원천 시그널 ID (감사 추적용)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Fill:
    """개별 체결 조각."""
    price: float
    qty: int
    executed_at: datetime
    fee: float = 0.0                     # 수수료 (실 발생분)


@dataclass
class OrderResult:
    """OrderManager 반환 · 감사 로그 저장 대상."""
    order_uuid: str
    broker_order_id: Optional[str]
    status: OrderStatus
    fills: list[Fill] = field(default_factory=list)
    avg_fill_price: Optional[float] = None
    filled_qty: int = 0
    remaining_qty: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    raw_response: Optional[dict] = None


@dataclass(frozen=True)
class Position:
    """종목별 보유 포지션 스냅샷."""
    ticker: str
    qty: int
    avg_price: float
    current_price: float
    unrealized_pnl: float                # 미실현 손익 (원 또는 USD, currency 별)
    unrealized_pnl_pct: float            # fraction (0.05 = +5%)
    currency: str = "KRW"                # KRW | USD


@dataclass(frozen=True)
class Balance:
    """계좌 잔고 스냅샷 (KRW·USD 통합 · 총 평가는 KRW 환산)."""
    cash_krw: float                      # 원화 매수 가능 현금
    cash_usd: float                      # USD 매수 가능 현금
    total_equity_krw: float              # KRW 환산 총 평가금액 (현금 + 포지션)
    positions: list[Position] = field(default_factory=list)
    fx_usd_krw: float = 1300.0           # 사용된 환율 (스냅샷 시점)


@dataclass(frozen=True)
class MarketInfo:
    """시장 상태 + 최근가."""
    ticker: str
    state: MarketState
    last_price: Optional[float]
    checked_at: datetime
