"""Trailing Stop 관리자 · Sprint 1 T48.

진입 후 최고가 지속 갱신 · giveback 초과 시 즉시 시장가 매도.

로직 (계획서 §3-2):
    peak_price = entry_price
    while position_open:
        current = get_current_price(ticker)
        if current > peak_price:
            peak_price = current
            continue

        giveback_pct = (current - peak_price) / peak_price
        hard_sl_pct = (current - entry_price) / entry_price

        if giveback_pct <= -trailing_giveback_pct: → sell (reason='trailing')
        if hard_sl_pct <= hard_stop_loss_pct:        → sell (reason='hard_sl')
        if now >= force_close_kst AND force_close_enabled: → sell (reason='force_close')

        sleep(poll_trailing_price_sec)

Sprint 1 은 in-process 관리 · Sprint 3 이후 Toss OCO 조건주문으로 이관 검토.

계획서: docs/plans/sniper/00-sprint1-plan.md §3-2 Trailing Stop 로직
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.execution.brokers.toss_client import TossClient, get_toss_client
from backend.services.db import get_session
from backend.services.models import SniperSignal

from .params import get_sniper_params

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class TrailingDecision:
    """단일 poll 판정 결과."""
    should_exit: bool
    reason: Optional[str] = None       # trailing · hard_sl · force_close · None
    current_price: Optional[float] = None
    peak_price: Optional[float] = None
    giveback_pct: Optional[float] = None
    hard_sl_pct: Optional[float] = None


def _parse_kst(hhmm: str) -> Optional[dtime]:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _is_force_close_time() -> bool:
    params = get_sniper_params()
    if not params.force_close_enabled:
        return False
    t = _parse_kst(params.force_close_kst)
    if t is None:
        return False
    now_kst = datetime.now(tz=_KST)
    return now_kst.time() >= t


def _fetch_current_price(ticker: str, toss_client: Optional[TossClient] = None) -> Optional[float]:
    client = toss_client or get_toss_client()
    try:
        data = client.prices([ticker])
        if isinstance(data, list) and data:
            item = data[0]
            price = item.get("price") or item.get("lastPrice")
            if isinstance(price, dict):
                price = price.get("lastPrice") or price.get("close")
            if price is not None:
                return float(price)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trailing price 조회 실패 · %s · %s", ticker, exc)
    return None


def evaluate_trailing(
    entry_price: float,
    peak_price: float,
    current_price: float,
) -> TrailingDecision:
    """순수 함수 · 파라미터 로드 후 청산 여부 판정.

    force_close 는 별도 판정 (`_is_force_close_time`).
    """
    params = get_sniper_params()

    if current_price > peak_price:
        return TrailingDecision(
            should_exit=False,
            current_price=current_price,
            peak_price=current_price,   # 갱신 후 값
        )

    giveback_pct = (current_price - peak_price) / peak_price if peak_price > 0 else 0.0
    hard_sl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    if giveback_pct <= -params.trailing_giveback_pct:
        return TrailingDecision(
            should_exit=True, reason="trailing",
            current_price=current_price, peak_price=peak_price,
            giveback_pct=giveback_pct, hard_sl_pct=hard_sl_pct,
        )
    if hard_sl_pct <= params.hard_stop_loss_pct:
        return TrailingDecision(
            should_exit=True, reason="hard_sl",
            current_price=current_price, peak_price=peak_price,
            giveback_pct=giveback_pct, hard_sl_pct=hard_sl_pct,
        )

    return TrailingDecision(
        should_exit=False,
        current_price=current_price, peak_price=peak_price,
        giveback_pct=giveback_pct, hard_sl_pct=hard_sl_pct,
    )


async def poll_trailing(
    signal_id: int,
    toss_client: Optional[TossClient] = None,
) -> Optional[TrailingDecision]:
    """단일 SniperSignal 에 대해 1회 trailing 판정 + peak 저장.

    force_close 시각 도달 시 최우선 청산 결정.
    Returns:
        TrailingDecision or None (row 없음/현재가 조회 실패)
    """
    async with get_session() as session:
        row = await session.get(SniperSignal, signal_id)
        if row is None or row.exit_order_uuid:      # 이미 청산됨
            return None
        entry_price = float(row.entry_price or 0)
        peak_price = float(row.peak_price or entry_price)
        ticker = row.ticker

    # 강제 청산 시각 (force_close_enabled 반영)
    if _is_force_close_time():
        return TrailingDecision(
            should_exit=True, reason="force_close",
            current_price=None, peak_price=peak_price,
        )

    current = _fetch_current_price(ticker, toss_client)
    if current is None:
        return None

    decision = evaluate_trailing(entry_price, peak_price, current)

    # peak 갱신은 항상 저장 (should_exit 여부 무관)
    if decision.peak_price is not None and decision.peak_price > peak_price:
        async with get_session() as session:
            row = await session.get(SniperSignal, signal_id)
            if row:
                row.peak_price = decision.peak_price

    return decision


async def open_positions() -> list[int]:
    """미청산 SniperSignal · 오래된 순."""
    async with get_session() as session:
        stmt = (
            select(SniperSignal.id)
            .where(SniperSignal.exit_order_uuid.is_(None))
            .where(SniperSignal.entry_order_uuid.isnot(None))
            .order_by(SniperSignal.detected_at.asc())
        )
        rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows]
