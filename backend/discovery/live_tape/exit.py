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
from backend.execution.audit import bot_entry_qty, record_direct_order
from backend.execution.order_manager import OrderManager
from backend.services.db import get_session
from backend.services.models import SniperSignal

from .params import get_sniper_params
from .trailing_stop import ENTRY_UNFILLED

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



def _exit_message(ticker: str, name, entry_price, exit_price, qty: int, pnl_pct, reason: str, order_uuid: str) -> tuple[str, str]:
    """실주문 청산 알림 (제목, 본문) · 1023-05."""
    from backend.services import alert_text as at

    pnl = f" {pnl_pct * 100:+.2f}%" if pnl_pct is not None else ""
    fact, keep = at.stock_fact(name, ticker)
    title = at.title("execution", fact, "🏁", keep=f"{keep} 팔림{pnl}")
    body = "\n".join([
        f"산 값 {at.won(entry_price)} → 판 값 {at.won(exit_price)} · {qty}주",
        f"이유: {at.EXIT_REASON.get(reason, at.esc(reason))}",
        f"주문 번호 {at.esc((order_uuid or '')[:12])}",
        at.link("execution"),
    ])
    return title, body

# 근사 수량 알림은 신호마다 1회 (프로세스 메모리 · 재시작하면 다시 1회)
_approx_alerted: set[int] = set()


async def _sellable_qty(signal_id: int, ticker: str, entry_uuid, entry_price: float, held_qty: int) -> int:
    """청산 수량 = min(계좌 보유, 봇이 산 수량) (1105-03).

    반환: >0 팔 수량 · 0 = 진입이 체결 0 으로 끝나 팔 것 없음 (신호를 entry_unfilled 로 끝냄) ·
    -1 = 봇 수량을 알 수 없음 (감사 행도 진입가도 없음 · 알림 뒤 다음 주기 재시도).
    """
    bot_qty = await bot_entry_qty(entry_uuid)
    if bot_qty is None:
        # 감사 행 없음 (1025-02 전 진입 · 기록 실패) → 한 번에 사는 금액 ÷ 진입가 로 근사
        per_order = float(get_sniper_params().per_order_krw)
        approx = int(per_order // entry_price) if entry_price > 0 else 0
        logger.warning(
            "[sniper·exit] 봇 매수 기록 없음 · 근사 수량 사용 · signal=%d · %s · 근사 %d주 · 보유 %d주",
            signal_id, ticker, approx, held_qty,
        )
        await _alert_approx_once(signal_id, ticker, approx, held_qty)
        if approx <= 0:
            return -1
        return min(held_qty, approx)
    if bot_qty == 0:
        async with get_session() as session:
            row = await session.get(SniperSignal, signal_id)
            if row and row.exit_order_uuid is None:
                row.reason = ENTRY_UNFILLED
        logger.warning("[sniper·exit] 진입 주문 체결 0 · 팔 것 없음 · signal=%d · %s", signal_id, ticker)
        return 0
    return min(held_qty, bot_qty)


async def _alert_approx_once(signal_id: int, ticker: str, approx: int, held_qty: int) -> None:
    if signal_id in _approx_alerted:
        return
    _approx_alerted.add(signal_id)
    try:
        from backend.services.notifier import TelegramNotifier
        body = (
            f"{ticker} 청산에서 봇이 산 수량 기록을 찾지 못했습니다. "
            f"한 번에 사는 금액 ÷ 산 가격으로 {approx}주를 짐작해 팝니다 (계좌 보유 {held_qty}주). "
            "짐작이 틀리면 봇 주식이 조금 남거나 직접 사신 주식이 조금 팔릴 수 있습니다."
        )
        if approx <= 0:
            body = f"{ticker} 청산에서 봇이 산 수량을 알 수 없어 팔지 않았습니다 (계좌 보유 {held_qty}주). 직접 확인해 주십시오."
        await TelegramNotifier().send_warning("청산 수량 짐작", body, category="execution")
    except Exception as exc:  # noqa: BLE001
        logger.debug("[sniper·exit] 근사 알림 실패 · %s", exc)


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

    # 1105-03 · 봇이 산 수량까지만 판다 (계좌의 같은 종목에 사용자가 직접 산 주식이 있어도 남김)
    sell_qty = await _sellable_qty(signal_id, ticker, entry_uuid, entry_price, pos.qty)
    if sell_qty <= 0:
        return ExitResult(
            ok=False, reason=ENTRY_UNFILLED if sell_qty == 0 else "bot_qty_unknown",
            sniper_signal_id=signal_id, trigger_reason=trigger_reason,
        )

    req = OrderRequest(
        ticker=ticker,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        qty=sell_qty,
        signal_source="sniper",
        signal_id=f"sniper-exit-{signal_id}-{trigger_reason}",
    )

    # gate-design-v1 §3-1 · 직접 호출 경로 감사 (매도 · SignalRouter 미경유)
    logger.warning(
        "[direct_order_unrouted] source=sniper · side=sell · ticker=%s · qty=%s · signal_id=%s",
        req.ticker, req.qty, req.signal_id,
    )
    try:
        result = order_manager.submit_order(req)
    except KillSwitchActive:
        # 1105-02 · 어댑터는 Kill Switch 가 켜져도 매도는 허용 (sell_allowed 기본 True).
        # 여기로 오는 것은 사람이 「매도도 멈춤」 (sell_allowed=False) 을 고른 경우뿐.
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

    await record_direct_order(order_manager, req, result)

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
        from backend.services.stock_names import lookup_kr_name

        name = await lookup_kr_name(ticker)
        title, body = _exit_message(ticker, name, entry_price, exit_price, result.filled_qty, pnl_pct, trigger_reason, result.order_uuid)
        await notifier.send_info(title, body, category="execution")
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
