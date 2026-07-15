"""Powder Keg APScheduler 잡 등록 · Phase 7-3 자동 감시.

지시서 §7-3 완료 기준:
    - 타입 B 공시 발생 시 리스트 제거 + 알림이 5분 내 발생한다.

잡:
  · powderkeg_events_poll   · 30분 주기 · DART 공시 폴링 · 자동 저장
  · powderkeg_triggers_run  · 5분 주기 · pending 이벤트 액션 처리 (Type A/B)

powderkeg_events_poll 은 lookback=1일 (30분 주기 시 정합) · watched_tickers=None
    (모든 매칭 저장 · 화약고 리스트 종목만 관심 · 나머지는 스크리너 후 정리).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def poll_events_job() -> dict[str, Any]:
    """30분 주기 · DART 이벤트 폴링."""
    from .collectors.events import poll_powderkeg_events
    try:
        return await poll_powderkeg_events(lookback_days=1, watched_tickers=None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[powderkeg.events_poll] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


async def process_triggers_job() -> dict[str, Any]:
    """5분 주기 · pending 이벤트 액션 처리."""
    from .triggers import process_pending_events
    try:
        return await process_pending_events(limit=200)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[powderkeg.triggers] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


def register_powderkeg_jobs(scheduler) -> None:
    """FastAPI lifespan 에서 호출."""
    scheduler.add_job(
        poll_events_job, "interval",
        minutes=30,
        id="powderkeg_events_poll",
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        process_triggers_job, "interval",
        minutes=5,
        id="powderkeg_triggers",
        max_instances=1, coalesce=True,
    )
    logger.info(
        "[powderkeg] jobs 등록 · events_poll=30m · triggers=5m "
        "(Type B 발생 시 리스트 즉시 제거)"
    )
