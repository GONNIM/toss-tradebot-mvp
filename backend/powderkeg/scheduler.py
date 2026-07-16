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


async def holding_expiry_job() -> dict[str, Any]:
    """일 1회 · holding_days_max (기본 365일) 경과 티켓 재평가 알림.

    지시서 §7-5 · 보유 기간 상한(기본 12개월) 경과 시 재평가 알림.
    """
    from .orders import check_holding_expiry
    try:
        expired = await check_holding_expiry()
        if expired:
            await _notify_expiry(expired)
        return {"expired_count": len(expired), "items": expired}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[powderkeg.holding_expiry] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


async def _notify_expiry(expired: list[dict]) -> None:
    """만료 티켓 Telegram 알림 (§7-5 재평가)."""
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        title = "🕐 화약고 보유 재평가 (12개월 경과)"
        lines = [
            f"  · {e['ticker']} · {e['age_days']}일 경과 (ticket #{e['ticket_id']})"
            for e in expired
        ]
        await notifier.send_warning(title, "\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[powderkeg.holding_expiry] Telegram 실패 · %s", exc)


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
    scheduler.add_job(
        holding_expiry_job, "cron",
        hour=8, minute=0, timezone="Asia/Seoul",
        id="powderkeg_holding_expiry",
        max_instances=1, coalesce=True,
    )
    logger.info(
        "[powderkeg] jobs 등록 · events_poll=30m · triggers=5m "
        "· holding_expiry=daily 08:00 KST (§7-5 12개월 재평가)"
    )
