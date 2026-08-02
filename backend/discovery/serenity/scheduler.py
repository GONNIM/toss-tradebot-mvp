"""Serenity APScheduler 잡 등록 · Phase L8 · 2026-08-02.

잡 (모두 KST):
  ① serenity_crawler_daily      — 매일 06:00 · 트윗 아카이브 sync (무비용)
  ② serenity_extractor_daily    — 매일 07:00 · z.ai signal 추출 (비용 · 안전 스위치)
  ③ serenity_scorer_daily       — 매일 08:00 · 15원칙 재계산 (무비용)
  ④ serenity_backtest_weekly    — 매주 월 00:00 · yfinance 백테스트 (무료 rate limit)

환경 스위치:
  SERENITY_CRON_ENABLED       (default true · 마스터 스위치)
  SERENITY_EXTRACTOR_CRON     (default false · z.ai 비용 안전장치 · 명시 활성 필요)

sector_leaders scheduler listener 가 executed/error 이벤트를 logs 테이블에 기록.
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _is_enabled(env_name: str, default: bool) -> bool:
    raw = os.environ.get(env_name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def _job_crawler() -> None:
    from backend.discovery.serenity.crawler import sync_tweets
    result = await sync_tweets()
    logger.info("[serenity] cron crawler · %s", result)


async def _job_extractor() -> None:
    if not os.environ.get("ZAI_API_KEY"):
        logger.warning("[serenity] cron extractor skip · ZAI_API_KEY 미설정")
        return
    from backend.discovery.serenity.extractor import process_pending_tweets
    result = await process_pending_tweets(batch_size=200, concurrency=4)
    logger.info("[serenity] cron extractor · %s", result)


async def _job_scorer() -> None:
    from backend.discovery.serenity.scorer import refresh_all_scores
    result = await refresh_all_scores()
    logger.info("[serenity] cron scorer · %s", result)


async def _job_backtest() -> None:
    from backend.discovery.serenity.backtest import refresh_backtests
    result = await refresh_backtests(batch_size=200, concurrency=4)
    logger.info("[serenity] cron backtest · %s", result)


def register_serenity_jobs(scheduler: AsyncIOScheduler) -> None:
    """Serenity 4 크론 등록 · env 스위치 존중.

    - SERENITY_CRON_ENABLED=false 면 전부 skip
    - SERENITY_EXTRACTOR_CRON=true 명시해야 extractor 활성 (z.ai 비용 방지)
    """
    if not _is_enabled("SERENITY_CRON_ENABLED", default=True):
        logger.info("[serenity] cron 마스터 비활성 · 등록 skip")
        return

    scheduler.add_job(
        _job_crawler,
        trigger=CronTrigger(hour=6, minute=0, timezone="Asia/Seoul"),
        id="serenity_crawler_daily",
        name="매일 06:00 KST · Serenity 트윗 아카이브 sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    if _is_enabled("SERENITY_EXTRACTOR_CRON", default=False):
        scheduler.add_job(
            _job_extractor,
            trigger=CronTrigger(hour=7, minute=0, timezone="Asia/Seoul"),
            id="serenity_extractor_daily",
            name="매일 07:00 KST · Serenity z.ai signal 추출 (비용 발생)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )
        logger.info("[serenity] cron extractor 활성 (SERENITY_EXTRACTOR_CRON=true)")
    else:
        logger.info(
            "[serenity] cron extractor skip · SERENITY_EXTRACTOR_CRON 명시 true 필요 (z.ai 비용)"
        )

    scheduler.add_job(
        _job_scorer,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"),
        id="serenity_scorer_daily",
        name="매일 08:00 KST · Serenity 15원칙 스코어 재계산",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    scheduler.add_job(
        _job_backtest,
        trigger=CronTrigger(
            day_of_week="mon", hour=0, minute=0, timezone="Asia/Seoul"
        ),
        id="serenity_backtest_weekly",
        name="매주 월 00:00 KST · Serenity yfinance 백테스트",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    logger.info("[serenity] cron 등록 완료 · 4 jobs (extractor 는 env 스위치 필요)")
