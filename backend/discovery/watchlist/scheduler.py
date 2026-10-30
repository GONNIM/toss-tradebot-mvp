"""Watchlist 야간 잡 스케줄러 · Sprint 2 T59.

APScheduler 잡 등록:
  · watchlist_news        5m interval  (RSS 9곳 · 상시)
  · watchlist_youtube     1h interval  (YouTube · 상시)
  · watchlist_assembly    1d @06:00    (국회 의안 · 아침 1회)
  · watchlist_gov_press   1h interval  (정부 RSS · 상시)
  · watchlist_dart_events_am/pm 08:20·20:40 KST (밈 감시가 저장한 DART 공시 읽기 · 1030-04)
  · watchlist_finalize    1d @08:30    (Top N 확정)
  · watchlist_rank_daily  1d @20:30 KST (토스 순위 하루 1회 저장 + 새 진입 신호 · 1030-04)
  · watchlist_rank_rt     매시 09:05~15:05 KST 평일 (20:30 집계가 없을 때의 대비 · 1030-04)
  (네이버 종토방 잡은 robots 금지라 등록하지 않는다 · naver_board.py 는 남기되 스케줄 없음 · 1030-04)

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


async def rank_daily_job() -> dict[str, Any]:
    """20:30 KST · 토스 순위 5종류 저장 + 새 진입 신호."""
    from .rank_signals import collect_rank_daily

    try:
        return await collect_rank_daily()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[watchlist_rank_daily] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


async def rank_realtime_job() -> dict[str, Any]:
    """장중 매시 · 그날 최고 순위 누적 (20:30 집계 없을 때 대비)."""
    from .rank_signals import collect_rank_realtime

    try:
        return await collect_rank_realtime()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[watchlist_rank_rt] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


async def dart_events_job() -> dict[str, Any]:
    """08:20·20:40 KST · 저장된 DART 공시 → 이벤트·주의 신호."""
    from .dart_events import collect_dart_events

    try:
        return await collect_dart_events()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[watchlist_dart_events] 실패 · %s", exc)
        return {"error": str(exc)[:200]}


def register_watchlist_jobs(scheduler) -> None:
    """FastAPI lifespan 에서 호출. 신호 수집·확정·순위 잡 등록 (종토방 제외)."""
    from .assembly import poll_assembly_bills
    from .gov_press import poll_gov_press
    from .news_rss import poll_news_rss
    from .youtube import poll_youtube_channels

    # 뉴스 RSS · 5분
    scheduler.add_job(
        poll_news_rss, "interval", minutes=5,
        id="watchlist_news", max_instances=1, coalesce=True,
    )

    # YouTube · 1시간
    scheduler.add_job(
        poll_youtube_channels, "interval", hours=1,
        id="watchlist_youtube", max_instances=1, coalesce=True,
    )

    # 국회 의안 · 매일 06:00 KST
    # 스케줄러가 Asia/Seoul 이라 시각은 KST 그대로 · timezone 도 명시 (1030-02 · 07-15 부터 UTC 로 적혀 15:00 늦게 돌았음)
    scheduler.add_job(
        poll_assembly_bills, "cron",
        hour=6, minute=0, timezone="Asia/Seoul",
        id="watchlist_assembly", max_instances=1,
    )

    # 정부 부처 RSS · 1시간
    scheduler.add_job(
        poll_gov_press, "interval", hours=1,
        id="watchlist_gov_press", max_instances=1, coalesce=True,
    )

    # Watchlist 확정 · 매일 08:30 KST (finalize 는 「오늘 KST」 목록을 만든다 · 23:30 에 돌면 끝난 날을 다시 씀)
    scheduler.add_job(
        finalize_watchlist_job, "cron",
        hour=8, minute=30, timezone="Asia/Seoul",
        id="watchlist_finalize", max_instances=1,
    )

    # DART 공시 읽기 · 08:20 (finalize 08:30 직전) · 20:40 (순위 잡 직후) · timezone 명시 (1030-02 교훈)
    for job_id, hour, minute in (("watchlist_dart_events_am", 8, 20), ("watchlist_dart_events_pm", 20, 40)):
        scheduler.add_job(
            dart_events_job, "cron",
            hour=hour, minute=minute, timezone="Asia/Seoul",
            id=job_id, max_instances=1,
        )

    # 토스 순위 하루 1회 · 20:30 KST (개인 순매수는 정규장 뒤 제공 · 20시경까지 변동)
    scheduler.add_job(
        rank_daily_job, "cron",
        hour=20, minute=30, timezone="Asia/Seoul",
        id="watchlist_rank_daily", max_instances=1,
    )

    # 장중 순위 누적 · 09:05~15:05 매시 평일
    scheduler.add_job(
        rank_realtime_job, "cron",
        day_of_week="mon-fri", hour="9-15", minute=5, timezone="Asia/Seoul",
        id="watchlist_rank_rt", max_instances=1,
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
        "[watchlist] jobs 등록 · news=5m · youtube=1h · "
        "assembly=daily 06:00 KST · gov_press=1h · dart_events=08:20·20:40 KST · finalize=daily 08:30 KST · "
        "rank_daily=20:30 KST · rank_rt=평일 09~15시 :05 · "
        "execute=%ds (활성창 09:00~09:30 KST 내부 판정)",
        _exec_sec,
    )
