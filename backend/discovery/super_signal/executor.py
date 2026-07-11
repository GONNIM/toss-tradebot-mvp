"""Super Signal Executor — v2 트랙 C Phase 3.

승격된 SuperSignal → 매수 진입 (SignalRouter 통과) → OCO 조건주문 자동 등록.
OCO: 익절+손절 원자 세팅 · 하나 체결 시 나머지 자동 취소.

스펙: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §6-1
     docs/plans/tradebot-mvp-v2/03-toss-openapi-integration.md §4
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.execution.brokers.toss_client import get_toss_client
from backend.execution.exceptions import ExecutionError, OrderRejected
from backend.execution.params import get_params_store
from backend.execution.signal_router import SignalEvent, get_signal_router
from backend.services.db import get_session
from backend.services.models import SuperSignal

logger = logging.getLogger(__name__)


_OCO_EXPIRE_DAYS = 30
_MAX_ENTRY_STRENGTH = 100


def _resolve_thresholds(ticker: str) -> tuple[float, float]:
    """params store 에서 종목/시그널 override 반영된 TP·SL 조회."""
    params = get_params_store().resolve(ticker=ticker, signal_source="super_signal")
    tp = params.take_profit_pct if params.take_profit_pct is not None else 0.07
    sl = params.stop_loss_pct if params.stop_loss_pct is not None else -0.04
    return tp, sl


def _round_price(ticker: str, price: float) -> str:
    """가격 문자열 변환 · KRX 정수, US 소수 2자리 (Toss decimal string)."""
    if ticker.isdigit() and len(ticker) == 6:
        return str(int(round(price)))
    return f"{price:.2f}"


def _client_oco_id(ticker: str) -> str:
    return f"ttboco-{uuid.uuid4().hex[:8]}"


async def execute_super_signal(super_signal: SuperSignal) -> dict:
    """SuperSignal → BUY (Router) → OCO 등록.

    Returns:
        {"router_result": ..., "oco_id": ..., "oco_request_id": ..., "skipped": ..., "error": ...}
    """
    result: dict = {"skipped": False}

    # 1) SignalRouter 로 매수 진입 (EXECUTION_ENABLED=false 시 None → skip)
    router = get_signal_router()
    if router is None:
        result["skipped"] = True
        result["reason"] = "execution_disabled"
        return result

    event = SignalEvent(
        ticker=super_signal.ticker,
        action="buy",
        strength=_MAX_ENTRY_STRENGTH,   # Super Signal 은 항상 최대 강도
        source="super_signal",
        signal_id=f"super-{super_signal.id}-{super_signal.ticker}",
        order_type="market",
        metadata={"intensity": super_signal.intensity, "sources": super_signal.sources},
    )
    order_result = await router.route(event)
    result["router_result"] = {
        "status": order_result.status.value if order_result else None,
        "broker_order_id": order_result.broker_order_id if order_result else None,
        "filled_qty": order_result.filled_qty if order_result else 0,
    }

    if order_result is None or order_result.status.value not in {"filled", "partial", "accepted"}:
        result["skipped"] = True
        result["reason"] = f"entry_not_open: {order_result.status.value if order_result else 'none'}"
        return result

    # 2) 실 체결가 확보 (없으면 entry skip)
    entry_price = order_result.avg_fill_price
    if entry_price is None:
        result["skipped"] = True
        result["reason"] = "no_entry_price"
        return result

    filled_qty = order_result.filled_qty or 0
    if filled_qty <= 0:
        result["skipped"] = True
        result["reason"] = "no_filled_qty"
        return result

    # 3) TP · SL 임계값 → 트리거 가격 계산
    tp_pct, sl_pct = _resolve_thresholds(super_signal.ticker)
    tp_price = entry_price * (1.0 + tp_pct)
    sl_price = entry_price * (1.0 + sl_pct)

    # 4) OCO 조건주문 등록 (Toss 실전 어댑터 사용 시에만)
    # Paper 어댑터는 OCO 미지원 · skip
    from backend.execution.brokers.toss_adapter import TossAdapter

    if not isinstance(router._om, TossAdapter):  # noqa: SLF001
        result["skipped"] = True
        result["reason"] = "paper_broker_no_oco"
        return result

    body = {
        "clientOrderId": _client_oco_id(super_signal.ticker),
        "type": "OCO",
        "symbol": super_signal.ticker,
        "quantity": str(filled_qty),
        "orderType": "LIMIT",
        "expireDate": (datetime.now(tz=timezone.utc) + timedelta(days=_OCO_EXPIRE_DAYS)).strftime("%Y-%m-%d"),
        "first": {
            "orderSide": "SELL",
            "triggerPrice": _round_price(super_signal.ticker, tp_price),
            "orderPrice": _round_price(super_signal.ticker, tp_price),
        },
        "second": {
            "orderSide": "SELL",
            "triggerPrice": _round_price(super_signal.ticker, sl_price),
            "orderPrice": _round_price(super_signal.ticker, sl_price),
        },
    }

    try:
        env = get_toss_client().create_conditional_order(body)
    except OrderRejected as exc:
        # duplicate-conditional-order 방어: 이미 있는 경우 로그만
        if exc.code == "duplicate-conditional-order":
            logger.info(
                "OCO duplicate · %s · 기존 유지", super_signal.ticker
            )
            result["skipped"] = True
            result["reason"] = "oco_duplicate"
            return result
        raise
    except ExecutionError as exc:
        result["error"] = str(exc)
        return result

    oco_data = env.result if isinstance(env.result, dict) else {}
    oco_id = oco_data.get("conditionalOrderId") or oco_data.get("id")
    result["oco_id"] = oco_id
    result["oco_request_id"] = env.request_id
    result["tp_price"] = _round_price(super_signal.ticker, tp_price)
    result["sl_price"] = _round_price(super_signal.ticker, sl_price)

    # SuperSignal 레코드 갱신
    async with get_session() as session:
        row = await session.get(SuperSignal, super_signal.id)
        if row:
            row.order_uuid = order_result.order_uuid if order_result else None
            row.oco_id = oco_id
            row.oco_status = "OPEN"
            # metadata_json 병합
            try:
                meta = json.loads(row.metadata_json) if row.metadata_json else {}
            except (TypeError, ValueError):
                meta = {}
            meta["oco"] = {
                "tp_price": result["tp_price"],
                "sl_price": result["sl_price"],
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "entry_price": entry_price,
                "request_id": env.request_id,
            }
            row.metadata_json = json.dumps(meta, ensure_ascii=False, default=str)

    logger.info(
        "🎯 OCO 등록 · %s · entry=%.2f · TP=%s · SL=%s · oco_id=%s",
        super_signal.ticker, entry_price, result["tp_price"], result["sl_price"], oco_id,
    )
    return result
