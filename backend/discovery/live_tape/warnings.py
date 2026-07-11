"""Warnings 필터 · Sprint 1 T42.

Toss GET /api/v1/stocks/{symbol}/warnings 실시간 조회 · 진입 차단 매핑.

진입 차단 warnings:
  · LIQUIDATION_TRADING (정리매매) — 즉시 배제 (무한 하락 리스크)
  · OVERHEATED (단기과열 지정) — 상투 리스크
  · INVESTMENT_WARNING · INVESTMENT_RISK — pump&dump 리스크
  · VI_* (VI 발동) — 이미 급등 완료 · 상투 리스크

허용 warnings:
  · STOCK_WARRANTS — 신주인수권 (일반적 · 문제 없음)

계획서: docs/plans/sniper/00-sprint1-plan.md §3-1 6단계 매수 방어
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.execution.brokers.toss_client import TossClient, get_toss_client

logger = logging.getLogger(__name__)


_BLOCK_TYPES = frozenset({
    "LIQUIDATION_TRADING",
    "OVERHEATED",
    "INVESTMENT_WARNING",
    "INVESTMENT_RISK",
    "VI_STATIC",
    "VI_DYNAMIC",
    "VI_STATIC_AND_DYNAMIC",
})


@dataclass(frozen=True)
class WarningsResult:
    ticker: str
    blocked: bool
    active_types: tuple[str, ...]
    checked_at: datetime


async def check_warnings(ticker: str, toss_client: Optional[TossClient] = None) -> WarningsResult:
    """단일 종목 warnings 조회 · 진입 차단 판정.

    API 실패 시 안전측 · blocked=True (진입 금지).
    """
    client = toss_client or get_toss_client()
    now = datetime.now(tz=timezone.utc)
    try:
        env = client.stock_warnings(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("warnings API 실패 · %s · %s · 안전측 진입 차단", ticker, exc)
        return WarningsResult(ticker=ticker, blocked=True, active_types=("api_error",), checked_at=now)

    items = env.result if isinstance(env.result, list) else []
    active: list[str] = []
    for item in items:
        w_type = item.get("warningType")
        if not w_type:
            continue
        # startDate ~ endDate 활성 판정 (KST date)
        start = item.get("startDate")
        end = item.get("endDate")
        today = now.astimezone(tz=None).strftime("%Y-%m-%d")   # local KST (macOS 서울)
        # naive 판정: startDate <= today <= endDate (endDate null 은 진행 중)
        if start and start > today:
            continue
        if end and end < today:
            continue
        active.append(w_type)

    blocked = any(w in _BLOCK_TYPES for w in active)
    if blocked:
        logger.info("warnings 차단 · %s · 활성 %s", ticker, active)
    return WarningsResult(
        ticker=ticker,
        blocked=blocked,
        active_types=tuple(active),
        checked_at=now,
    )
