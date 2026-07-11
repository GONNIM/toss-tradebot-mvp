"""Sniper 실주문 매수 · Sprint 1 T44.

candidate 감지 → 6단계 방어 통과 → TossAdapter.submit_order(MARKET BUY)
→ SniperSignal INSERT → 텔레그램 알림 → OrderResult 반환.

6단계 방어 (계획서 §3-1):
1. Kill Switch active? → 스킵
2. 시드 잔여 < per_order_krw? → 스킵 (InsufficientBalance 사전 방지)
3. 동시 보유 max_concurrent_positions 도달? → 스킵
4. 정규장 시간? (active_start_kst ≤ now < active_end_kst) → 밖이면 스킵
5. 이미 오늘 진입한 종목? → 스킵 (동일 종목 1일 1회)
6. 종목별 warnings (VI · 단기과열 · 정리매매)? → 스킵

계획서: docs/plans/sniper/00-sprint1-plan.md §3-1 (6단계 매수 방어)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.execution import (
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    MarketClosed,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.brokers.toss_adapter import TossAdapter
from backend.execution.kill_switch import KillSwitch, get_kill_switch
from backend.execution.order_manager import OrderManager
from backend.services.db import get_session
from backend.services.models import SniperSignal

from .params import get_sniper_params
from .scoring import CandidateSignal
from .warnings import check_warnings

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class EntryResult:
    """진입 시도 결과."""
    ok: bool
    reason: Optional[str] = None                  # 실패 사유 (skip 이유)
    order_uuid: Optional[str] = None
    broker_order_id: Optional[str] = None
    filled_qty: int = 0
    entry_price: Optional[float] = None
    sniper_signal_id: Optional[int] = None


def _parse_kst_time(hhmm: str) -> Optional[dtime]:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _is_in_active_window(params) -> bool:
    now_kst = datetime.now(tz=_KST)
    if now_kst.weekday() >= 5:      # 토·일 · KRX 정규장 없음
        return False
    start = _parse_kst_time(params.active_start_kst)
    end = _parse_kst_time(params.active_end_kst)
    if start is None or end is None:
        return False
    t = now_kst.time()
    return start <= t < end


async def _count_concurrent_positions(order_manager: OrderManager) -> int:
    try:
        balance = order_manager.get_balance()
        return len([p for p in balance.positions if p.qty > 0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("잔고 조회 실패 · %s · 안전측 최대치 반환", exc)
        return 999


async def _seed_remaining_krw(order_manager: OrderManager, seed_cap_krw: float) -> float:
    """시드 대비 잔여 KRW · Paper 는 cash_krw · Toss 는 buying-power KRW."""
    try:
        balance = order_manager.get_balance()
        return min(seed_cap_krw, balance.cash_krw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("잔고 조회 실패 · %s", exc)
        return 0.0


async def _already_entered_today(ticker: str) -> bool:
    """오늘 KST 기준 · 해당 티커로 이미 진입한 이력 있는지."""
    now_kst = datetime.now(tz=_KST)
    today_kst_start = datetime.combine(now_kst.date(), dtime.min, tzinfo=_KST)
    today_utc = today_kst_start.astimezone(timezone.utc)
    async with get_session() as session:
        stmt = (
            select(func.count(SniperSignal.id))
            .where(SniperSignal.ticker == ticker)
            .where(SniperSignal.detected_at >= today_utc)
        )
        count = int((await session.execute(stmt)).scalar() or 0)
    return count > 0


def _price_to_qty(per_order_krw: float, price: float) -> int:
    if price <= 0:
        return 0
    qty = int(per_order_krw // price)
    return max(0, qty)


async def execute_entry(
    candidate: CandidateSignal,
    order_manager: OrderManager,
    *,
    kill_switch: Optional[KillSwitch] = None,
    signal_metadata: Optional[dict] = None,
) -> EntryResult:
    """candidate → 매수 실행. 6단계 방어 후 순차 진입.

    Args:
        kill_switch: 명시 시 이 인스턴스 사용, 없으면 프로세스 싱글턴.
                     테스트 격리 · adapter 와 동일 인스턴스 공유 시 사용.

    Returns:
        EntryResult · ok=False 시 reason 명시.
    """
    params = get_sniper_params()
    ks = kill_switch or get_kill_switch()

    # ── 방어 1: Kill Switch ─────────────────────
    if ks.is_active():
        logger.info("[sniper·entry] Kill Switch active · skip · %s", candidate.ticker)
        return EntryResult(ok=False, reason="kill_switch_active")

    # ── 방어 2: 시드 잔여 ──────────────────────
    seed_remain = await _seed_remaining_krw(order_manager, params.seed_cap_krw)
    if seed_remain < params.per_order_krw:
        return EntryResult(
            ok=False,
            reason=f"seed_remain<{params.per_order_krw:.0f}(remain={seed_remain:.0f})",
        )

    # ── 방어 3: 동시 보유 상한 ────────────────
    n_positions = await _count_concurrent_positions(order_manager)
    if n_positions >= params.max_concurrent_positions:
        return EntryResult(
            ok=False,
            reason=f"positions_full({n_positions}/{params.max_concurrent_positions})",
        )

    # ── 방어 4: 정규장 시간 ──────────────────
    if not _is_in_active_window(params):
        return EntryResult(
            ok=False,
            reason=f"outside_active_window({params.active_start_kst}~{params.active_end_kst})",
        )

    # ── 방어 5: 동일 티커 오늘 진입 이력 ─────
    if await _already_entered_today(candidate.ticker):
        return EntryResult(ok=False, reason="already_entered_today")

    # ── 방어 6: warnings 실시간 확인 ────────
    warnings = await check_warnings(candidate.ticker)
    if warnings.blocked:
        return EntryResult(
            ok=False,
            reason=f"warnings_blocked({','.join(warnings.active_types)})",
        )

    # ── 진입 · qty 계산 · 시장가 매수 ────────
    price = candidate.last_price
    qty = _price_to_qty(params.per_order_krw, price)
    if qty <= 0:
        return EntryResult(ok=False, reason=f"qty=0(price={price:.2f})")

    req = OrderRequest(
        ticker=candidate.ticker,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=qty,
        signal_source="sniper",
        signal_id=f"sniper-{candidate.ticker}-{int(candidate.detected_at.timestamp())}",
    )

    try:
        result = order_manager.submit_order(req)
    except KillSwitchActive:
        return EntryResult(ok=False, reason="kill_switch_active_at_submit")
    except MarketClosed as exc:
        return EntryResult(ok=False, reason=f"market_closed:{exc.code}")
    except InsufficientBalance as exc:
        return EntryResult(ok=False, reason=f"insufficient:{exc.code}")
    except ExecutionError as exc:
        logger.exception("[sniper·entry] execution error · %s", exc)
        return EntryResult(ok=False, reason=f"execution_error:{exc}")

    if result.status not in {OrderStatus.FILLED, OrderStatus.PARTIAL_FILL, OrderStatus.ACCEPTED}:
        return EntryResult(
            ok=False,
            reason=f"order_status:{result.status.value}",
            order_uuid=result.order_uuid,
            broker_order_id=result.broker_order_id,
        )

    # ── SniperSignal INSERT ────────────────
    entry_price = result.avg_fill_price or price
    async with get_session() as session:
        signal_row = SniperSignal(
            ticker=candidate.ticker,
            detected_at=candidate.detected_at,
            tape_score=candidate.tape_score,
            rank_velocity=candidate.rank_velocity_score,
            trades_intensity=candidate.trades_intensity_score,
            orderbook_imbalance=candidate.orderbook_score,
            entry_order_uuid=result.order_uuid,
            entry_price=entry_price,
            peak_price=entry_price,
            reason=None,
        )
        session.add(signal_row)
        await session.flush()
        signal_id = signal_row.id

    logger.info(
        "🎯 [sniper·entry] %s · qty=%d · price=%.2f · order_uuid=%s · signal_id=%d",
        candidate.ticker, qty, entry_price, result.order_uuid, signal_id,
    )

    # ── 텔레그램 알림 (best-effort) ───────
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        title = f"🎯 SNIPER 진입 · {candidate.ticker}"
        body = (
            f"진입가 {entry_price:,.2f} · 수량 {qty}주 (약 {entry_price*qty:,.0f}원)\n"
            f"tape_score {candidate.tape_score:.2f} (rank {candidate.rank_velocity_score:.1f} · "
            f"trades {candidate.trades_intensity_score:.1f} · book {candidate.orderbook_score:.1f})\n"
            f"return {(candidate.return_pct or 0)*100:+.2f}%\n"
            f"order_uuid <code>{result.order_uuid[:12]}</code>"
        )
        await notifier.send_info(title, body)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[sniper·entry] 텔레그램 실패 · %s", exc)

    return EntryResult(
        ok=True,
        order_uuid=result.order_uuid,
        broker_order_id=result.broker_order_id,
        filled_qty=result.filled_qty,
        entry_price=entry_price,
        sniper_signal_id=signal_id,
    )
