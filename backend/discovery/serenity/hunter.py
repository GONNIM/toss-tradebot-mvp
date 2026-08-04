"""Serenity Hunter · 게이트 + 폐기 + 중간경고 판정 · Phase L14 v6 (2026-08-04).

Step A: is_gate_open()/is_deprecation_triggered()/mid_gate_excess_warning() 뼈대.
        (실제 hunter_rows() 는 Step C 에서 구현 · Fable 5 3차 순서 강제)

Fable 5 3차 (1) 반영 (v6 §2.7):
    is_gate_open() = 5조건 AND
      1. valid_backtest_events >= 50 (v6 §2.7 상폐 포함)
      2. IWM benchmark row >= 50 영업일 (Fable 5 6차 · 개수 · 수익률 아님)
      3. MAX(computed_at) >= now - 48h
      4. health.warn == false (stale 방어)
      5. is_deprecation_triggered() == false (폐기 강제 close)

Fable 5 3차 (2) 반영 (v6 §2.8):
    is_deprecation_triggered() =
      · valid >= 150
      · AND avg(raw_return_3d - benchmark_iwm_return_3d) - SLIPPAGE - COST <= 0
        (v6 D1: raw · 판정 계층에서 1회 차감)
      · AND DEPRECATION_OVERRIDE_TICKET is None

Fable 5 3차 (2d) 반영 (v6 §2.9):
    mid_gate_excess_warning() =
      · 50 <= valid < 150 AND avg(raw - bench_iwm) - SLIPPAGE - COST <= 0
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select

from backend.discovery.serenity.constants import (
    COST_ROUND_TRIP_PCT,
    DEPRECATION_EVENTS_MIN,
    DEPRECATION_OVERRIDE_TICKET,
    GATE_EVENTS_MIN,
    SLIPPAGE_PCT,
)
from backend.services.db import get_session
from backend.services.models import SerenityBacktest, SerenityBenchmarkPrice

logger = logging.getLogger(__name__)


async def _count_valid_backtests() -> int:
    """v6 §2.7 valid = price_at_signal not null AND (return_3d not null OR delisting_flag=true)."""
    async with get_session() as session:
        return int((await session.execute(
            select(func.count()).select_from(SerenityBacktest).where(
                SerenityBacktest.price_at_signal.is_not(None),
                (SerenityBacktest.return_3d.is_not(None)) | (SerenityBacktest.delisting_flag.is_(True)),
            )
        )).scalar_one())


async def _count_benchmark_rows(symbol: str) -> int:
    async with get_session() as session:
        return int((await session.execute(
            select(func.count()).select_from(SerenityBenchmarkPrice).where(
                SerenityBenchmarkPrice.symbol == symbol
            )
        )).scalar_one())


async def _last_backtest_freshness() -> Optional[datetime]:
    async with get_session() as session:
        return (await session.execute(
            select(func.max(SerenityBacktest.computed_at))
        )).scalar_one_or_none()


async def _avg_excess_iwm_3d_adjusted() -> Optional[float]:
    """v6 D1: raw excess (bench 차감) - SLIPPAGE - COST · 판정 계층 1회 차감.

    valid 이벤트만 대상 (상폐 포함 · return_3d 이 있어야 계산 가능).
    """
    async with get_session() as session:
        rows = list((await session.execute(
            select(SerenityBacktest.return_3d, SerenityBacktest.benchmark_iwm_return_3d)
            .where(SerenityBacktest.price_at_signal.is_not(None))
            .where(SerenityBacktest.return_3d.is_not(None))
            .where(SerenityBacktest.benchmark_iwm_return_3d.is_not(None))
        )).all())
    if not rows:
        return None
    diffs = [r[0] - r[1] for r in rows]
    raw_excess = sum(diffs) / len(diffs)
    # 판정 계층 1회 차감 (Fable 5 4차 D1 · v6 §2.8)
    return round(raw_excess - SLIPPAGE_PCT - COST_ROUND_TRIP_PCT, 2)


async def is_deprecation_triggered() -> bool:
    """폐기 조건 판정 (v6 §2.8 · Fable 5 3차 (2) · IWM 단독).

    True → hunter_rows() 자동 빈 배열 · 리스트 사라짐 (배너 아님).
    재개: RISK-PRINCIPLES §11 이력 + constants.DEPRECATION_OVERRIDE_TICKET 변경.
    """
    if DEPRECATION_OVERRIDE_TICKET is not None:
        # 재개 트리거 · 폐기 무효화
        return False
    valid = await _count_valid_backtests()
    if valid < DEPRECATION_EVENTS_MIN:
        return False
    adjusted = await _avg_excess_iwm_3d_adjusted()
    if adjusted is None:
        return False
    return adjusted <= 0


async def is_gate_open(health_warn: bool = False) -> tuple[bool, list[str]]:
    """v6 §2.7 하드 게이트 5조건 AND.

    반환: (open: bool, close_reasons: list[str])
    Step B UI 는 open=false 시 HunterEmptyGate 렌더.
    """
    reasons: list[str] = []

    valid = await _count_valid_backtests()
    if valid < GATE_EVENTS_MIN:
        reasons.append(f"insufficient_valid_events ({valid}/{GATE_EVENTS_MIN})")

    iwm_rows = await _count_benchmark_rows("IWM")
    if iwm_rows < GATE_EVENTS_MIN:
        reasons.append(f"insufficient_benchmark_rows_iwm ({iwm_rows}/{GATE_EVENTS_MIN})")

    last_computed = await _last_backtest_freshness()
    if last_computed is None or last_computed < datetime.utcnow() - timedelta(hours=48):
        reasons.append("stale_backtest (computed_at > 48h)")

    if health_warn:
        reasons.append("health_warn")

    if await is_deprecation_triggered():
        reasons.append("deprecation_triggered")

    return (len(reasons) == 0, reasons)


async def mid_gate_excess_warning() -> bool:
    """v6 §2.9 · 50 <= valid < 150 AND avg(raw - bench_iwm) - SLIPPAGE - COST <= 0.

    True → UI 리스트 상단 적색 배너 상시.
    """
    valid = await _count_valid_backtests()
    if valid < GATE_EVENTS_MIN or valid >= DEPRECATION_EVENTS_MIN:
        return False
    adjusted = await _avg_excess_iwm_3d_adjusted()
    if adjusted is None:
        return False
    return adjusted <= 0
