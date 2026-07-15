"""Watchlist 야간 잡 스케줄러 · Sprint 2 T59.

APScheduler 잡 등록:
  · watchlist_news        5m interval  (RSS · 상시)
  · watchlist_boards      30m interval (Naver 종토방 · 상시 · 정규장 중 부하 유의)
  · watchlist_youtube     1h interval  (YouTube · 상시)
  · watchlist_assembly    1d @06:00    (국회 의안 · 아침 1회)
  · watchlist_gov_press   1h interval  (정부 RSS · 상시)
  · watchlist_finalize    1d @08:30    (Week 2 placeholder · v1 no-op)

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T59
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def finalize_watchlist_job() -> dict[str, Any]:
    """08:30 KST Watchlist 확정 잡 · Week 2 T61 실체.

    scheduler 로부터 호출 · trade_date 자동 산출 (KST 오늘).
    """
    from .finalize import finalize_watchlist

    try:
        return await finalize_watchlist()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[watchlist_finalize] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


async def execute_watchlist_job() -> dict[str, Any]:
    """09:00~09:30 KST 개장 실행 잡 · Week 3 T64.

    30초 주기로 실행 · 활성창 밖이면 즉시 skip · watchlist_execute_enabled=false 시 skip.
    """
    from .execute import execute_watchlist_scan

    try:
        return await execute_watchlist_scan()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[watchlist_execute] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


def register_watchlist_jobs(scheduler) -> None:
    """FastAPI lifespan 에서 호출. 야간 신호 수집 잡 6개 등록."""
    from .assembly import poll_assembly_bills
    from .gov_press import poll_gov_press
    from .naver_board import poll_naver_boards
    from .news_rss import poll_news_rss
    from .youtube import poll_youtube_channels

    # 뉴스 RSS · 5분
    scheduler.add_job(
        poll_news_rss, "interval", minutes=5,
        id="watchlist_news", max_instances=1, coalesce=True,
    )

    # Naver 종토방 · 30분
    scheduler.add_job(
        poll_naver_boards, "interval", minutes=30,
        id="watchlist_boards", max_instances=1, coalesce=True,
    )

    # YouTube · 1시간
    scheduler.add_job(
        poll_youtube_channels, "interval", hours=1,
        id="watchlist_youtube", max_instances=1, coalesce=True,
    )

    # 국회 의안 · 매일 06:00 KST (UTC 21:00 전일)
    scheduler.add_job(
        poll_assembly_bills, "cron",
        hour=21, minute=0,  # UTC · KST 06:00
        id="watchlist_assembly", max_instances=1,
    )

    # 정부 부처 RSS · 1시간
    scheduler.add_job(
        poll_gov_press, "interval", hours=1,
        id="watchlist_gov_press", max_instances=1, coalesce=True,
    )

    # Watchlist 확정 · 매일 08:30 KST (UTC 23:30 전일)
    scheduler.add_job(
        finalize_watchlist_job, "cron",
        hour=23, minute=30,  # UTC · KST 08:30
        id="watchlist_finalize", max_instances=1,
    )

    # Watchlist 개장 실행 · 30초 interval · 잡 내부에서 활성창 판정
    from backend.discovery.live_tape.params import get_sniper_params
    _params = get_sniper_params()
    _exec_sec = max(15, _params.watchlist_execute_poll_sec)
    scheduler.add_job(
        execute_watchlist_job, "interval",
        seconds=_exec_sec,
        id="watchlist_execute", max_instances=1, coalesce=True,
    )

    logger.info(
        "[watchlist] jobs 등록 · news=5m · boards=30m · youtube=1h · "
        "assembly=daily 06:00 KST · gov_press=1h · finalize=daily 08:30 KST · "
        "execute=%ds (활성창 09:00~09:30 KST 내부 판정)",
        _exec_sec,
    )
