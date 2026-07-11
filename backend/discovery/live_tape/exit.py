"""Sniper 실주문 매도 · Sprint 1 T49.

trailing 발동 (또는 hard_sl · force_close) → TossAdapter/PaperAdapter.submit_order(MARKET SELL)
→ SniperSignal UPDATE (exit_order_uuid · exit_price · pnl_pct · reason)
→ 텔레그램 알림 → 청산 완료.

이후 오케스트레이터(T50) 는 신호 대기 loop 로 복귀.

계획서: docs/plans/sniper/00-sprint1-plan.md §3-2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.execution import (
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from backend.execution.order_manager import OrderManager
from backend.services.db import get_session
from backend.services.models import SniperSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExitResult:
    ok: bool
    reason: Optional[str] = None
    order_uuid: Optional[str] = None
    broker_order_id: Optional[str] = None
    exit_price: Optional[float] = None
    filled_qty: int = 0
    pnl_pct: Optional[float] = None
    sniper_signal_id: Optional[int] = None
    trigger_reason: Optional[str] = None       # trailing · hard_sl · force_close


async def execute_exit(
    signal_id: int,
    order_manager: OrderManager,
    trigger_reason: str,
) -> ExitResult:
    """SniperSignal 청산. 시장가 매도 · UPDATE · 알림.

    Args:
        signal_id: SniperSignal row id
        order_manager: OMI adapter (Paper/Toss)
        trigger_reason: trailing · hard_sl · force_close
    """
    async with get_session() as session:
        row = await session.get(SniperSignal, signal_id)
        if row is None:
            return ExitResult(ok=False, reason="signal_not_found", sniper_signal_id=signal_id, trigger_reason=trigger_reason)
        if row.exit_order_uuid is not None:
            return ExitResult(
                ok=False, reason="already_exited",
                sniper_signal_id=signal_id,
                trigger_reason=trigger_reason,
            )
        ticker = row.ticker
        entry_price = float(row.entry_price or 0)
        entry_uuid = row.entry_order_uuid

    # 실제 보유 수량 확보 (Paper: state · Toss: holdings)
    try:
        pos = order_manager.get_position(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_position 실패 · %s · %s", ticker, exc)
        return ExitResult(
            ok=False, reason=f"position_lookup_failed:{exc}",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )
    if pos is None or pos.qty <= 0:
        # 보유 없음 · 이미 청산되었거나 이력 불일치. 안전측 signal 상태 표시.
        async with get_session() as session:
            row = await session.get(SniperSignal, signal_id)
            if row and row.exit_order_uuid is None:
                row.reason = "no_position"
        return ExitResult(
            ok=False, reason="no_position",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )

    req = OrderRequest(
        ticker=ticker,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        qty=pos.qty,
        signal_source="sniper",
        signal_id=f"sniper-exit-{signal_id}-{trigger_reason}",
    )

    try:
        result = order_manager.submit_order(req)
    except KillSwitchActive:
        # 매도는 Kill Switch 발동 상태에서도 안전측 시도가 필요 · 하지만 Router 는 차단.
        # adapter 레벨에서 KS active 이면 예외. 여기까지 오면 실 청산 실패.
        logger.warning("[sniper·exit] Kill Switch active · %s 청산 실패", ticker)
        return ExitResult(
            ok=False, reason="kill_switch_blocks_sell",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )
    except InsufficientBalance as exc:
        return ExitResult(
            ok=False, reason=f"insufficient:{exc.code}",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )
    except ExecutionError as exc:
        logger.exception("[sniper·exit] execution error")
        return ExitResult(
            ok=False, reason=f"execution_error:{exc}",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )

    exit_price = result.avg_fill_price
    if exit_price is None and result.status in {OrderStatus.FILLED, OrderStatus.PARTIAL_FILL}:
        exit_price = result.fills[0].price if result.fills else None

    pnl_pct = None
    if entry_price > 0 and exit_price is not None:
        pnl_pct = exit_price / entry_price - 1.0

    # SniperSignal UPDATE
    async with get_session() as session:
        row = await session.get(SniperSignal, signal_id)
        if row:
            row.exit_order_uuid = result.order_uuid
            row.exit_price = exit_price
            row.pnl_pct = pnl_pct
            row.reason = trigger_reason

    logger.info(
        "🏁 [sniper·exit] %s · qty=%d · exit=%.2f · pnl=%s%% · reason=%s · order=%s",
        ticker, result.filled_qty, exit_price or 0,
        f"{pnl_pct*100:+.2f}" if pnl_pct is not None else "-",
        trigger_reason, result.order_uuid,
    )

    # 텔레그램
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        pnl_str = f"{pnl_pct*100:+.2f}%" if pnl_pct is not None else "-"
        title = f"🏁 SNIPER 청산 · {ticker} · {pnl_str}"
        body = (
            f"청산가 {exit_price:,.2f} · 수량 {result.filled_qty}주\n"
            f"진입 {entry_price:,.2f} → 청산 {exit_price:,.2f}\n"
            f"사유: {trigger_reason}\n"
            f"order_uuid <code>{result.order_uuid[:12]}</code>"
        )
        await notifier.send_info(title, body)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[sniper·exit] 텔레그램 실패 · %s", exc)

    return ExitResult(
        ok=True,
        order_uuid=result.order_uuid,
        broker_order_id=result.broker_order_id,
        exit_price=exit_price,
        filled_qty=result.filled_qty,
        pnl_pct=pnl_pct,
        sniper_signal_id=signal_id,
        trigger_reason=trigger_reason,
    )
