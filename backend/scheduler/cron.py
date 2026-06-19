"""APScheduler cron 실행기 — Crazy + Moonshot 일일 실행.

스케줄 (KST):
  - 06:30 Crazy Picks (미국 장 마감 직후)
  - 16:50 Moonshot Picks (미국 장 시작 10분 전, 서머타임 기준)
  - 06:00 universe 갱신

기동:
    python -m backend.scheduler.cron

systemd 또는 PM2 로 daemonize.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def job_crazy_picks():
    """06:30 KST Crazy Picks 실행."""
    logger.info("[cron] Crazy Picks 시작")
    try:
        # Phase D 통합 후 활성화
        # from backend.discovery.crazy_picks import run_crazy_picks
        # from backend.discovery.universe import load_universe_from_db
        # universe = await load_universe_from_db(crazy_only=True)
        # clients = build_clients()
        # picks = await run_crazy_picks(universe, clients, top_n=10)
        # await save_picks_to_db(picks)
        # await notify_telegram(picks)
        logger.info("[cron] Crazy Picks — placeholder (Phase J 통합)")
    except Exception as e:
        logger.error(f"[cron] Crazy Picks 실패: {e}", exc_info=True)


async def job_moonshot_picks():
    """16:50 KST Moonshot Picks 실행."""
    logger.info("[cron] Moonshot Picks 시작")
    try:
        logger.info("[cron] Moonshot Picks — placeholder (Phase J 통합)")
    except Exception as e:
        logger.error(f"[cron] Moonshot Picks 실패: {e}", exc_info=True)


async def job_universe_refresh():
    """06:00 KST universe 갱신."""
    logger.info("[cron] Universe refresh 시작")
    try:
        logger.info("[cron] Universe refresh — placeholder (Phase J 통합)")
    except Exception as e:
        logger.error(f"[cron] Universe refresh 실패: {e}", exc_info=True)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    scheduler.add_job(
        job_universe_refresh,
        CronTrigger(hour=6, minute=0),
        id="universe_refresh",
        name="Universe 갱신",
        replace_existing=True,
    )
    scheduler.add_job(
        job_crazy_picks,
        CronTrigger(hour=6, minute=30),
        id="crazy_picks",
        name="Crazy Picks 06:30 KST",
        replace_existing=True,
    )
    scheduler.add_job(
        job_moonshot_picks,
        CronTrigger(hour=16, minute=50),
        id="moonshot_picks",
        name="Moonshot Picks 16:50 KST",
        replace_existing=True,
    )

    return scheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("[cron] Scheduler 시작 — 등록 job:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.id}: {job.name} → next run {job.next_run_time}")

    # 종료 시그널 대기
    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("[cron] Shutdown signal received")
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop.wait()
    scheduler.shutdown(wait=True)
    logger.info("[cron] Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
