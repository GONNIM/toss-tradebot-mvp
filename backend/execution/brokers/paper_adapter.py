"""PaperAdapter — v2 트랙 C Phase 1.

시뮬 어댑터. 실 자본 없이 계약 검증 및 시나리오 재생.
- 시세: Toss 실 API 위임 (실 시장 반영)
- 체결: 시뮬 (MARKET 즉시 · LIMIT PENDING → 수동/tick 매칭)
- 잔고: backend/data/paper_balance.json 로컬 저장

초기 자본:
1. 최초 기동 시 Toss GET /buying-power (KRW+USD) + /holdings sync
2. Toss 실패 시 env `PAPER_INITIAL_CASH` fallback (기본 10_000_000)
3. 사용자 UI 재싱크 버튼으로 언제든 재동기화

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §6-2
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.services import config

from ..exceptions import (
    BrokerCommunicationError,
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
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
from .toss_client import TossClient, get_toss_client

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BALANCE_PATH = _PROJECT_ROOT / "backend" / "data" / "paper_balance.json"
_DEFAULT_INITIAL_CASH_KRW = 10_000_000.0
_KRX_FEE_RATE = 0.00015     # 대략치 · Phase 2 GET /commissions 로 보정
_US_FEE_RATE = 0.0025


@dataclass
class _PaperState:
    cash_krw: float
    cash_usd: float
    fx_usd_krw: float
    positions: dict[str, dict] = field(default_factory=dict)   # ticker → {qty, avg_price, currency}
    pending_orders: dict[str, dict] = field(default_factory=dict)  # broker_order_id → order snapshot
    filled_orders: dict[str, dict] = field(default_factory=dict)   # broker_order_id → result snapshot
    idempotency: dict[str, dict] = field(default_factory=dict)  # order_uuid → OrderResult snapshot (sync 캐시)
    order_seq: int = 0
    synced_at: Optional[str] = None
    synced_from: str = "env-fallback"


class PaperAdapter(OrderManager):
    """OrderManager 시뮬 구현."""

    broker_kind = BrokerKind.PAPER

    def __init__(
        self,
        *,
        toss_client: Optional[TossClient] = None,
        kill_switch: Optional[KillSwitch] = None,
        state_path: Optional[Path] = None,
        fx_usd_krw: float = 1370.0,
    ):
        self._toss = toss_client or get_toss_client()
        self._ks = kill_switch or get_kill_switch()
        self._state_path = state_path or _DEFAULT_BALANCE_PATH
        self._lock = threading.RLock()
        self._default_fx = fx_usd_krw
        self._state = self._load_or_init()

    # ─── 상태 로드/저장 ───
    def _load_or_init(self) -> _PaperState:
        with self._lock:
            if self._state_path.exists():
                try:
                    raw = json.loads(self._state_path.read_text(encoding="utf-8"))
                    return _PaperState(
                        cash_krw=float(raw.get("cash_krw", 0.0)),
                        cash_usd=float(raw.get("cash_usd", 0.0)),
                        fx_usd_krw=float(raw.get("fx_usd_krw", self._default_fx)),
                        positions=raw.get("positions") or {},
                        pending_orders=raw.get("pending_orders") or {},
                        filled_orders=raw.get("filled_orders") or {},
                        idempotency=raw.get("idempotency") or {},
                        order_seq=int(raw.get("order_seq", 0)),
                        synced_at=raw.get("synced_at"),
                        synced_from=raw.get("synced_from", "env-fallback"),
                    )
                except (json.JSONDecodeError, OSError) as exc:
                    logger.error("paper_balance.json 파싱 실패 — %s · 재초기화", exc)

            # 신규: Toss sync 시도 → 실패 시 env fallback
            state = self._sync_from_toss_or_fallback()
            self._persist(state)
            return state

    def _persist(self, state: Optional[_PaperState] = None) -> None:
        state = state or self._state
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _sync_from_toss_or_fallback(self) -> _PaperState:
        try:
            return self._sync_from_toss()
        except Exception as exc:  # noqa: BLE001
            fallback_cash = float(config.get("PAPER_INITIAL_CASH") or _DEFAULT_INITIAL_CASH_KRW)
            logger.warning(
                "Toss sync 실패 — env fallback (PAPER_INITIAL_CASH=%s KRW). 이유: %s",
                fallback_cash,
                exc,
            )
            return _PaperState(
                cash_krw=fallback_cash,
                cash_usd=0.0,
                fx_usd_krw=self._default_fx,
                synced_at=datetime.now(timezone.utc).isoformat(),
                synced_from="env-fallback",
            )

    def _sync_from_toss(self) -> _PaperState:
        krw = self._toss.buying_power("KRW") or {}
        usd = self._toss.buying_power("USD") or {}
        cash_krw = float(krw.get("cashBuyingPower", 0))
        cash_usd = float(usd.get("cashBuyingPower", 0))

        holdings = self._toss.holdings() or {}
        items = holdings.get("items") if isinstance(holdings, dict) else []
        positions: dict[str, dict] = {}
        for item in items or []:
            symbol = item.get("symbol")
            if not symbol:
                continue
            positions[symbol] = {
                "qty": int(float(item.get("quantity", 0))),
                "avg_price": float(item.get("averagePurchasePrice", 0)),
                "currency": item.get("currency", "KRW"),
            }

        return _PaperState(
            cash_krw=cash_krw,
            cash_usd=cash_usd,
            fx_usd_krw=self._default_fx,
            positions=positions,
            synced_at=datetime.now(timezone.utc).isoformat(),
            synced_from="toss",
        )

    def resync_from_toss(self) -> _PaperState:
        """사용자 UI '재싱크' 버튼용. 성공 시 반환, 실패 시 예외."""
        with self._lock:
            state = self._sync_from_toss()
            # pending/filled orders 는 유지 (재싱크는 자본만 재설정)
            state.pending_orders = self._state.pending_orders
            state.filled_orders = self._state.filled_orders
            state.order_seq = self._state.order_seq
            self._state = state
            self._persist()
            logger.info(
                "PaperAdapter 재싱크 완료 · cash_krw=%s · positions=%d",
                state.cash_krw,
                len(state.positions),
            )
            return state

    def reset(self, *, cash_krw: Optional[float] = None) -> _PaperState:
        """UI '수동 리셋' — cash만 재설정, 포지션은 유지 or 초기화 옵션."""
        with self._lock:
            new_cash = cash_krw if cash_krw is not None else _DEFAULT_INITIAL_CASH_KRW
            self._state = _PaperState(
                cash_krw=new_cash,
                cash_usd=0.0,
                fx_usd_krw=self._default_fx,
                positions={},
                pending_orders={},
                filled_orders={},
                order_seq=0,
                synced_at=datetime.now(timezone.utc).isoformat(),
                synced_from="user-manual-reset",
            )
            self._persist()
            return self._state

    # ─── 시세 조회 ───
    def _current_price(self, ticker: str) -> Optional[float]:
        try:
            data = self._toss.prices([ticker])
            if isinstance(data, list) and data:
                p = data[0].get("price") or data[0].get("lastPrice")
                return float(p) if p is not None else None
            if isinstance(data, dict):
                p = data.get("price") or data.get("lastPrice")
                return float(p) if p is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("실 시세 조회 실패 (%s) — %s", ticker, exc)
        return None

    # ─── 수수료 ───
    @staticmethod
    def _fee_rate(currency: str) -> float:
        return _US_FEE_RATE if currency.upper() == "USD" else _KRX_FEE_RATE

    @staticmethod
    def _guess_currency(ticker: str) -> str:
        """KRX 6자리 숫자 → KRW, 그 외 → USD (Phase 1 근사)."""
        return "KRW" if ticker.isdigit() and len(ticker) == 6 else "USD"

    # ─── OMI 구현 ───
    def submit_order(self, req: OrderRequest) -> OrderResult:
        # 1) Kill Switch 우선 체크
        if self._ks.is_active():
            raise KillSwitchActive(self._ks.status().reason or "kill switch active")

        # 2) idempotency — in-process 캐시 우선 (sync 컨텍스트 안전)
        cached = self._state.idempotency.get(req.order_uuid)
        if cached is not None:
            logger.info(
                "idempotency hit · uuid=%s · status=%s", req.order_uuid[:8], cached.get("status")
            )
            return self._restore_from_snapshot(req.order_uuid, cached)

        with self._lock:
            self._state.order_seq += 1
            seq = self._state.order_seq
            broker_order_id = f"paper-{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}-{seq:04d}"

            currency = self._guess_currency(req.ticker)
            now = datetime.now(tz=timezone.utc)

            # ─── MARKET → 즉시 체결 ───
            if req.order_type == OrderType.MARKET:
                # SELL 은 시세 조회 전 포지션 존재 여부 우선 검증
                if req.side == OrderSide.SELL:
                    held = self._state.positions.get(req.ticker)
                    if not held or held.get("qty", 0) < req.qty:
                        have = held.get("qty", 0) if held else 0
                        raise InsufficientBalance(
                            "insufficient-position",
                            f"매도 필요 {req.qty}주 > 보유 {have}주 ({req.ticker})",
                        )
                price = self._current_price(req.ticker)
                if price is None:
                    return OrderResult(
                        order_uuid=req.order_uuid,
                        broker_order_id=broker_order_id,
                        status=OrderStatus.ERROR,
                        error_code="price-unavailable",
                        error_message=f"현재가 조회 실패: {req.ticker}",
                        submitted_at=now,
                        completed_at=now,
                    )
                return self._settle(req, broker_order_id, price, currency, now)

            # ─── LIMIT → 즉시 매칭 시도 · 미매칭이면 PENDING ───
            if req.order_type == OrderType.LIMIT:
                if req.price is None:
                    raise ExecutionError("LIMIT 주문에는 price 필수")
                mid = self._current_price(req.ticker)
                fill_ok = mid is not None and (
                    (req.side == OrderSide.BUY and mid <= req.price)
                    or (req.side == OrderSide.SELL and mid >= req.price)
                )
                if fill_ok:
                    return self._settle(req, broker_order_id, req.price, currency, now)
                # PENDING 유지
                snapshot = {
                    "order_uuid": req.order_uuid,
                    "ticker": req.ticker,
                    "side": req.side.value,
                    "order_type": req.order_type.value,
                    "qty": req.qty,
                    "price": req.price,
                    "currency": currency,
                    "submitted_at": now.isoformat(),
                }
                self._state.pending_orders[broker_order_id] = snapshot
                result = OrderResult(
                    order_uuid=req.order_uuid,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.ACCEPTED,
                    remaining_qty=req.qty,
                    submitted_at=now,
                    raw_response={"paper": True, "reason": "limit-pending"},
                )
                self._cache_idempotency(result)
                self._persist()
                return result

            raise ExecutionError(f"미지원 order_type: {req.order_type}")

    def _settle(
        self,
        req: OrderRequest,
        broker_order_id: str,
        price: float,
        currency: str,
        now: datetime,
    ) -> OrderResult:
        """즉시 전량 체결 시나리오."""
        fee_rate = self._fee_rate(currency)
        notional = price * req.qty
        fee = notional * fee_rate

        # 잔고 처리
        if req.side == OrderSide.BUY:
            required = notional + fee
            cash_attr = "cash_krw" if currency == "KRW" else "cash_usd"
            cash = getattr(self._state, cash_attr)
            if required > cash:
                raise InsufficientBalance(
                    "insufficient-cash",
                    f"매수 필요 {required:.2f} > 잔고 {cash:.2f} ({currency})",
                )
            setattr(self._state, cash_attr, cash - required)
            self._apply_buy(req.ticker, req.qty, price, currency)
        else:  # SELL
            held = self._state.positions.get(req.ticker)
            if not held or held.get("qty", 0) < req.qty:
                have = held.get("qty", 0) if held else 0
                raise InsufficientBalance(
                    "insufficient-position",
                    f"매도 필요 {req.qty}주 > 보유 {have}주 ({req.ticker})",
                )
            proceeds = notional - fee
            cash_attr = "cash_krw" if currency == "KRW" else "cash_usd"
            setattr(self._state, cash_attr, getattr(self._state, cash_attr) + proceeds)
            self._apply_sell(req.ticker, req.qty)

        fill = Fill(price=price, qty=req.qty, executed_at=now, fee=fee)
        result = OrderResult(
            order_uuid=req.order_uuid,
            broker_order_id=broker_order_id,
            status=OrderStatus.FILLED,
            fills=[fill],
            avg_fill_price=price,
            filled_qty=req.qty,
            remaining_qty=0,
            submitted_at=now,
            completed_at=now,
            raw_response={"paper": True, "currency": currency, "fee_rate": fee_rate},
        )
        self._state.filled_orders[broker_order_id] = {
            "order_uuid": req.order_uuid,
            "ticker": req.ticker,
            "side": req.side.value,
            "qty": req.qty,
            "fill_price": price,
            "fee": fee,
            "completed_at": now.isoformat(),
        }
        self._cache_idempotency(result)
        self._persist()
        return result

    def _cache_idempotency(self, result: OrderResult) -> None:
        """OrderResult → 스냅샷 dict (JSON 직렬화 가능한 형태로)."""
        self._state.idempotency[result.order_uuid] = {
            "broker_order_id": result.broker_order_id,
            "status": result.status.value,
            "avg_fill_price": result.avg_fill_price,
            "filled_qty": result.filled_qty,
            "remaining_qty": result.remaining_qty,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "submitted_at": result.submitted_at.isoformat() if result.submitted_at else None,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            "fills": [
                {
                    "price": f.price,
                    "qty": f.qty,
                    "executed_at": f.executed_at.isoformat(),
                    "fee": f.fee,
                }
                for f in result.fills
            ],
        }

    def _restore_from_snapshot(self, order_uuid: str, snap: dict) -> OrderResult:
        from datetime import datetime as _dt

        def _parse(s):
            return _dt.fromisoformat(s) if s else None

        fills = [
            Fill(
                price=f["price"],
                qty=f["qty"],
                executed_at=_parse(f["executed_at"]),
                fee=f.get("fee", 0.0),
            )
            for f in snap.get("fills", [])
        ]
        return OrderResult(
            order_uuid=order_uuid,
            broker_order_id=snap.get("broker_order_id"),
            status=OrderStatus(snap.get("status", "error")),
            fills=fills,
            avg_fill_price=snap.get("avg_fill_price"),
            filled_qty=snap.get("filled_qty", 0),
            remaining_qty=snap.get("remaining_qty", 0),
            error_code=snap.get("error_code"),
            error_message=snap.get("error_message"),
            submitted_at=_parse(snap.get("submitted_at")),
            completed_at=_parse(snap.get("completed_at")),
        )

    def _apply_buy(self, ticker: str, qty: int, price: float, currency: str) -> None:
        pos = self._state.positions.get(ticker)
        if not pos:
            self._state.positions[ticker] = {
                "qty": qty,
                "avg_price": price,
                "currency": currency,
            }
            return
        total_qty = pos["qty"] + qty
        avg = (pos["qty"] * pos["avg_price"] + qty * price) / total_qty
        pos["qty"] = total_qty
        pos["avg_price"] = avg
        pos["currency"] = currency

    def _apply_sell(self, ticker: str, qty: int) -> None:
        pos = self._state.positions.get(ticker)
        if not pos:
            return
        pos["qty"] -= qty
        if pos["qty"] <= 0:
            self._state.positions.pop(ticker, None)

    def cancel_order(self, broker_order_id: str) -> bool:
        with self._lock:
            snapshot = self._state.pending_orders.pop(broker_order_id, None)
            if snapshot is None:
                return False
            self._state.filled_orders[broker_order_id] = {
                **snapshot,
                "status": OrderStatus.CANCELED.value,
                "canceled_at": datetime.now(timezone.utc).isoformat(),
            }
            self._persist()
            return True

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        with self._lock:
            if broker_order_id in self._state.pending_orders:
                snap = self._state.pending_orders[broker_order_id]
                return OrderResult(
                    order_uuid=snap["order_uuid"],
                    broker_order_id=broker_order_id,
                    status=OrderStatus.ACCEPTED,
                    remaining_qty=snap["qty"],
                )
            if broker_order_id in self._state.filled_orders:
                snap = self._state.filled_orders[broker_order_id]
                status_value = snap.get("status", OrderStatus.FILLED.value)
                try:
                    status = OrderStatus(status_value)
                except ValueError:
                    status = OrderStatus.FILLED
                return OrderResult(
                    order_uuid=snap["order_uuid"],
                    broker_order_id=broker_order_id,
                    status=status,
                    avg_fill_price=snap.get("fill_price"),
                    filled_qty=snap.get("qty", 0),
                    remaining_qty=0,
                )
            raise OrderNotFound(f"paper broker_order_id={broker_order_id}")

    def get_position(self, ticker: str) -> Optional[Position]:
        with self._lock:
            pos = self._state.positions.get(ticker)
            if not pos or pos["qty"] <= 0:
                return None
            current = self._current_price(ticker) or pos["avg_price"]
            unreal = (current - pos["avg_price"]) * pos["qty"]
            unreal_pct = (current / pos["avg_price"] - 1.0) if pos["avg_price"] else 0.0
            return Position(
                ticker=ticker,
                qty=pos["qty"],
                avg_price=pos["avg_price"],
                current_price=current,
                unrealized_pnl=unreal,
                unrealized_pnl_pct=unreal_pct,
                currency=pos.get("currency", "KRW"),
            )

    def get_balance(self) -> Balance:
        with self._lock:
            positions: list[Position] = []
            total_pos_krw = 0.0
            for ticker in list(self._state.positions.keys()):
                p = self.get_position(ticker)
                if p is None:
                    continue
                positions.append(p)
                value = p.current_price * p.qty
                if p.currency == "USD":
                    value *= self._state.fx_usd_krw
                total_pos_krw += value

            total_equity_krw = (
                self._state.cash_krw
                + self._state.cash_usd * self._state.fx_usd_krw
                + total_pos_krw
            )
            return Balance(
                cash_krw=self._state.cash_krw,
                cash_usd=self._state.cash_usd,
                total_equity_krw=total_equity_krw,
                positions=positions,
                fx_usd_krw=self._state.fx_usd_krw,
            )

    def get_market_info(self, ticker: str) -> MarketInfo:
        price = self._current_price(ticker)
        # Phase 1: 시장 시간 판정은 단순 (Phase 2 에서 market-calendar API 로 정교화)
        return MarketInfo(
            ticker=ticker,
            state=MarketState.REGULAR if price is not None else MarketState.CLOSED,
            last_price=price,
            checked_at=datetime.now(tz=timezone.utc),
        )

    def health_check(self) -> bool:
        try:
            self._toss.access_token()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("PaperAdapter health_check 실패 — %s", exc)
            return False

    # ─── 노출용 유틸리티 (API 라우트 · UI 용) ───
    def snapshot_state(self) -> dict:
        with self._lock:
            return asdict(self._state)
