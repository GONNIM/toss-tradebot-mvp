"""TossAdapter — v2 트랙 C Phase 2 (실전 어댑터).

토스증권 Open API v1.2.2 를 통한 실 주문/취소/조회.
- 인증: TossClient (OAuth2 CC · 캐시 · pre-emptive refresh)
- 주문 idempotency: clientOrderId = "ttb-{uuid8}" (10분 유효 · 36자 · [a-zA-Z0-9_-])
- 응답 { result } 래퍼 자동 언랩 (2026-07-10 실측 계약)
- 에러 매핑 → OMI 예외 계층 (TossClient._raise_from_response 참조)
- **주문 안전 하드 상한**: EXECUTION_MAX_ORDER_AMOUNT (기본 100_000 원) — 어댑터 레벨 강제

스펙: docs/plans/tradebot-mvp-v2/{02-omi-interface-spec.md §6-3, 03-toss-openapi-integration.md}
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.services import config

from ..exceptions import (
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    MarketClosed,
    OrderNotFound,
)
from ..kill_switch import KillSwitch, get_kill_switch
from ..models import (
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
from ..order_manager import OrderManager
from .rate_limiter import retry_with_backoff
from .toss_client import TossClient, TossEnvelope, get_toss_client

logger = logging.getLogger(__name__)

_CLIENT_ORDER_PREFIX = os.environ.get("TOSS_CLIENT_ORDER_PREFIX", "ttb")
_CLIENT_ORDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,36}$")
_MAX_ORDER_AMOUNT_KRW = float(os.environ.get("EXECUTION_MAX_ORDER_AMOUNT", "100000"))
_HIGH_VALUE_THRESHOLD_KRW = 100_000_000  # 1억 이상 confirmHighValueOrder=true 필요

# Toss OrderStatus (10종) → OMI OrderStatus 매핑
_TOSS_TO_OMI: dict[str, OrderStatus] = {
    "PENDING": OrderStatus.ACCEPTED,
    "PENDING_CANCEL": OrderStatus.ACCEPTED,
    "PENDING_REPLACE": OrderStatus.ACCEPTED,
    "PARTIAL_FILLED": OrderStatus.PARTIAL_FILL,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "CANCEL_REJECTED": OrderStatus.REJECTED,
    "REPLACE_REJECTED": OrderStatus.REJECTED,
    "REPLACED": OrderStatus.ACCEPTED,  # 원 order 대체 · 신규 orderId 발급
}


def _map_toss_status(raw: Optional[str]) -> OrderStatus:
    """Toss status → OMI status. Unknown 은 ACCEPTED 로 정규화 후 상위 UPDATE 대기."""
    if not raw:
        return OrderStatus.ACCEPTED
    return _TOSS_TO_OMI.get(raw.upper(), OrderStatus.ACCEPTED)


def _make_client_order_id(order_uuid: str) -> str:
    """OMI order_uuid → Toss clientOrderId.

    36자 · [a-zA-Z0-9_-] 규칙 준수 · 10분 유효.
    예: ttb-{uuid8}  (13자, 여유 충분)
    """
    short = order_uuid.replace("-", "")[:8]
    coid = f"{_CLIENT_ORDER_PREFIX}-{short}"
    if not _CLIENT_ORDER_ID_RE.match(coid):
        raise ExecutionError(f"clientOrderId 규칙 위반: {coid}")
    return coid


def _guess_currency(ticker: str) -> str:
    return "KRW" if ticker.isdigit() and len(ticker) == 6 else "USD"


class TossAdapter(OrderManager):
    """Toss Open API 실전 어댑터."""

    broker_kind = BrokerKind.TOSS

    def __init__(
        self,
        *,
        toss_client: Optional[TossClient] = None,
        kill_switch: Optional[KillSwitch] = None,
        max_order_amount_krw: float = _MAX_ORDER_AMOUNT_KRW,
    ):
        self._toss = toss_client or get_toss_client()
        self._ks = kill_switch or get_kill_switch()
        self._max_order_amount_krw = max_order_amount_krw
        self._lock = threading.RLock()
        # order_uuid → orderId 매핑 (idempotency 캐시 · 서버 재기동 시 audit 재구성)
        self._uuid_to_order_id: dict[str, str] = {}
        # FX 캐시 (환율 조회 최소화)
        self._fx_usd_krw: float = 1370.0
        self._fx_fetched_at: float = 0.0

    # ═══════════════════════════════════════════════════════════════
    # OrderManager 구현
    # ═══════════════════════════════════════════════════════════════
    def submit_order(self, req: OrderRequest) -> OrderResult:
        # 1) Kill Switch
        if self._ks.is_active():
            raise KillSwitchActive(self._ks.status().reason or "kill switch active")

        # 2) 정규장 게이팅 (Toss 422 order-hours-closed 방어선)
        from ..market_calendar import get_market_calendar

        if not get_market_calendar().is_regular_hours(req.ticker):
            raise MarketClosed(
                "local-market-closed",
                f"{req.ticker} 정규장 외 시간 · 로컬 게이팅",
            )

        # 3) 어댑터 레벨 하드 상한 (실 자본 안전장치)
        currency = _guess_currency(req.ticker)
        estimated_krw = self._estimate_order_krw(req, currency)
        if estimated_krw > self._max_order_amount_krw:
            raise InsufficientBalance(
                "hard-cap-max-order-amount",
                f"주문액 {estimated_krw:,.0f}원 > 어댑터 상한 {self._max_order_amount_krw:,.0f}원",
            )

        # 3) idempotency — 같은 order_uuid 재제출 시 서버 조회로 상태 반환
        with self._lock:
            existing_order_id = self._uuid_to_order_id.get(req.order_uuid)
        if existing_order_id:
            logger.info(
                "idempotency: 같은 order_uuid=%s · 서버 조회로 대체", req.order_uuid[:8]
            )
            return self._fetch_and_map(existing_order_id, req.order_uuid)

        # 4) 요청 본문 조립
        body: dict = {
            "clientOrderId": _make_client_order_id(req.order_uuid),
            "symbol": req.ticker,
            "side": req.side.value.upper(),
            "orderType": req.order_type.value.upper(),
            "timeInForce": "DAY",
            "quantity": str(req.qty),
        }
        if req.order_type == OrderType.LIMIT:
            if req.price is None:
                raise ExecutionError("LIMIT 주문에는 price 필수")
            body["price"] = str(req.price)
        # 1억 이상 confirm 플래그 (하드 상한이 앞서 걸러도 방어)
        if estimated_krw >= _HIGH_VALUE_THRESHOLD_KRW:
            body["confirmHighValueOrder"] = True

        # 5) 실 API 호출 · 429/5xx 자동 재시도
        env: TossEnvelope
        try:
            env = retry_with_backoff(lambda: self._toss.create_order(body))
        except InsufficientBalance:
            raise
        except OrderNotFound:
            raise
        except ExecutionError:
            raise

        # 6) 응답 → OrderResult
        result = self._env_to_result(env, req.order_uuid)
        if result.broker_order_id:
            with self._lock:
                self._uuid_to_order_id[req.order_uuid] = result.broker_order_id
        return result

    def cancel_order(self, broker_order_id: str) -> bool:
        try:
            env = self._toss.cancel_order(broker_order_id)
            data = env.result if isinstance(env.result, dict) else {}
            status = _map_toss_status(data.get("status"))
            return status in (OrderStatus.CANCELED, OrderStatus.ACCEPTED)  # PENDING_CANCEL 접수 성공도 True
        except OrderNotFound:
            return False
        except ExecutionError as exc:
            logger.warning("cancel_order 실패 · %s · %s", broker_order_id, exc)
            return False

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        env = self._toss.get_order(broker_order_id)
        return self._env_to_result(env, order_uuid=self._reverse_uuid(broker_order_id))

    def get_position(self, ticker: str) -> Optional[Position]:
        try:
            holdings = self._toss.holdings(symbol=ticker) or {}
        except ExecutionError as exc:
            logger.warning("holdings(%s) 실패 — %s", ticker, exc)
            return None
        items = holdings.get("items") or []
        for item in items:
            if item.get("symbol") != ticker:
                continue
            qty = int(float(item.get("quantity", 0)))
            if qty <= 0:
                continue
            avg = float(item.get("averagePurchasePrice", 0))
            last = float(item.get("lastPrice", 0)) or avg
            currency = item.get("currency", "KRW")
            unreal = (last - avg) * qty
            unreal_pct = (last / avg - 1.0) if avg else 0.0
            return Position(
                ticker=ticker,
                qty=qty,
                avg_price=avg,
                current_price=last,
                unrealized_pnl=unreal,
                unrealized_pnl_pct=unreal_pct,
                currency=currency,
            )
        return None

    def get_balance(self) -> Balance:
        try:
            bp_krw = self._toss.buying_power("KRW") or {}
            bp_usd = self._toss.buying_power("USD") or {}
            holdings = self._toss.holdings() or {}
        except ExecutionError as exc:
            logger.warning("get_balance 실패 — %s", exc)
            return Balance(
                cash_krw=0.0, cash_usd=0.0, total_equity_krw=0.0,
                positions=[], fx_usd_krw=self._fx_usd_krw,
            )

        cash_krw = float(bp_krw.get("cashBuyingPower", 0))
        cash_usd = float(bp_usd.get("cashBuyingPower", 0))
        fx = self._current_fx()

        positions: list[Position] = []
        for item in holdings.get("items") or []:
            symbol = item.get("symbol")
            qty = int(float(item.get("quantity", 0)))
            if not symbol or qty <= 0:
                continue
            avg = float(item.get("averagePurchasePrice", 0))
            last = float(item.get("lastPrice", 0)) or avg
            currency = item.get("currency", "KRW")
            unreal = (last - avg) * qty
            unreal_pct = (last / avg - 1.0) if avg else 0.0
            positions.append(
                Position(
                    ticker=symbol,
                    qty=qty,
                    avg_price=avg,
                    current_price=last,
                    unrealized_pnl=unreal,
                    unrealized_pnl_pct=unreal_pct,
                    currency=currency,
                )
            )

        # holdings 요약에서 총 평가 사용 (정확)
        mv = holdings.get("marketValue") or {}
        amount = mv.get("amount") or {}
        pos_krw = float(amount.get("krw", 0)) + float(amount.get("usd", 0)) * fx

        total = cash_krw + cash_usd * fx + pos_krw
        return Balance(
            cash_krw=cash_krw,
            cash_usd=cash_usd,
            total_equity_krw=total,
            positions=positions,
            fx_usd_krw=fx,
        )

    def get_market_info(self, ticker: str) -> MarketInfo:
        from ..market_calendar import get_market_calendar

        state = get_market_calendar().state_for(ticker)
        try:
            data = self._toss.prices([ticker])
            price: Optional[float] = None
            if isinstance(data, list) and data:
                p = data[0].get("price") or data[0].get("lastPrice")
                price = float(p) if p is not None else None
        except ExecutionError as exc:
            logger.warning("prices(%s) 실패 — %s", ticker, exc)
            price = None
        return MarketInfo(
            ticker=ticker,
            state=state,
            last_price=price,
            checked_at=datetime.now(tz=timezone.utc),
        )

    def health_check(self) -> bool:
        try:
            self._toss.access_token()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("TossAdapter health_check 실패 — %s", exc)
            return False

    # ═══════════════════════════════════════════════════════════════
    # 내부 헬퍼
    # ═══════════════════════════════════════════════════════════════
    def _estimate_order_krw(self, req: OrderRequest, currency: str) -> float:
        """주문 예상 KRW 환산액 (하드 상한 판정용)."""
        if req.price is not None:
            base = float(req.price) * req.qty
        else:
            # 시세로 근사
            mi = self.get_market_info(req.ticker)
            base = (mi.last_price or 0.0) * req.qty
        if currency == "USD":
            base *= self._current_fx()
        return base

    def _current_fx(self, max_age_sec: float = 300.0) -> float:
        import time as _t

        now = _t.time()
        if now - self._fx_fetched_at < max_age_sec:
            return self._fx_usd_krw
        try:
            data = self._toss.get("/api/v1/exchange-rate", use_account_header=False)
            # 실측 스키마 미정 · 안전 파싱
            if isinstance(data, dict):
                usd = data.get("USD") or data.get("usd") or data.get("KRW") or data.get("krw")
                if isinstance(usd, (int, float)):
                    self._fx_usd_krw = float(usd)
                elif isinstance(usd, dict):
                    v = usd.get("rate") or usd.get("value")
                    if isinstance(v, (int, float)):
                        self._fx_usd_krw = float(v)
        except Exception as exc:  # noqa: BLE001
            logger.debug("환율 조회 실패 · 캐시 유지 · %s", exc)
        self._fx_fetched_at = now
        return self._fx_usd_krw

    def _fetch_and_map(self, order_id: str, order_uuid: str) -> OrderResult:
        env = self._toss.get_order(order_id)
        return self._env_to_result(env, order_uuid)

    def _reverse_uuid(self, order_id: str) -> str:
        """orderId 로 order_uuid 조회 (Phase 2 어차피 audit 에서 잡을 수 있음)."""
        with self._lock:
            for k, v in self._uuid_to_order_id.items():
                if v == order_id:
                    return k
        return ""

    def _env_to_result(self, env: TossEnvelope, order_uuid: str) -> OrderResult:
        """Toss Order 응답 → OMI OrderResult."""
        data = env.result if isinstance(env.result, dict) else {}
        toss_status = data.get("status") or "PENDING"
        status = _map_toss_status(toss_status)
        order_id = data.get("orderId")

        # 체결 정보
        exec_info = data.get("execution") or {}
        filled_qty = int(float(exec_info.get("filledQuantity", 0) or 0))
        remaining = int(float(exec_info.get("remainingQuantity", 0) or 0))
        avg_fill = None
        if exec_info.get("averagePrice") is not None:
            try:
                avg_fill = float(exec_info["averagePrice"])
            except (TypeError, ValueError):
                avg_fill = None

        fills: list[Fill] = []
        # Toss 응답에 개별 체결 리스트가 있으면 파싱 (실측 후 정교화)
        for f in exec_info.get("fills") or []:
            try:
                fills.append(
                    Fill(
                        price=float(f.get("price", 0)),
                        qty=int(float(f.get("quantity", 0))),
                        executed_at=datetime.fromisoformat(f["executedAt"]) if f.get("executedAt") else datetime.now(timezone.utc),
                        fee=float(f.get("fee", 0) or 0),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("fill 파싱 스킵 · %s", exc)

        # raw_response 에 request_id + rate limit 포함
        raw = {
            "request_id": env.request_id,
            "rate_limit": env.rate_limit,
            "toss_status": toss_status,
            "response": data,
        }

        # 시각 파싱
        submitted_at = None
        completed_at = None
        if data.get("orderedAt"):
            try:
                submitted_at = datetime.fromisoformat(data["orderedAt"])
            except (TypeError, ValueError):
                pass
        if data.get("canceledAt"):
            try:
                completed_at = datetime.fromisoformat(data["canceledAt"])
            except (TypeError, ValueError):
                pass

        return OrderResult(
            order_uuid=order_uuid,
            broker_order_id=order_id,
            status=status,
            fills=fills,
            avg_fill_price=avg_fill,
            filled_qty=filled_qty,
            remaining_qty=remaining,
            error_code=None,
            error_message=None,
            submitted_at=submitted_at,
            completed_at=completed_at,
            raw_response=raw,
        )
