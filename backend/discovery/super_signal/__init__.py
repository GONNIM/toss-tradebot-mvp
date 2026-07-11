"""Super Signal — v2 트랙 C Phase 3.

다중 시그널 병합기 · 30일 window · 2+ source 히트 시 승격 · OCO 조건주문 자동 등록.

스펙: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §6-1
"""
from __future__ import annotations

from .executor import execute_super_signal
from .merger import get_recent_super_signals, promote_recent
from .scoring import SOURCE_WEIGHTS, compute_intensity
from .signal_hit import record_hit

__all__ = [
    "promote_recent",
    "get_recent_super_signals",
    "execute_super_signal",
    "compute_intensity",
    "SOURCE_WEIGHTS",
    "record_hit",
]


async def promote_and_execute() -> list[dict]:
    """오케스트레이션 헬퍼 · promote_recent → execute_super_signal 순차."""
    import logging
    logger = logging.getLogger(__name__)

    promoted = await promote_recent()
    results: list[dict] = []
    for ss in promoted:
        try:
            r = await execute_super_signal(ss)
            r["ticker"] = ss.ticker
            r["intensity"] = ss.intensity
            results.append(r)
        except Exception as exc:  # noqa: BLE001
            logger.exception("execute_super_signal 실패 · %s", ss.ticker)
            results.append({"ticker": ss.ticker, "error": str(exc)})
    return results
