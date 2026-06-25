"""Meme Watch APScheduler 잡 등록 (Phase 1a + 1b).

잡 (모두 KST):
  ① meme_universe_weekly   — 매 일요일 03:00 — universe 재빌드 (Phase 1a)
  ② meme_volume_us_daily   — 매일 06:00 — US Russell 2000 일봉 snapshot (Phase 1b)

후속 Phase 에서 추가:
  ③ meme_social_5min       — 5분마다 (장중) — Reddit/Stocktwits/Trends
  ④ meme_short_daily       — 매일 06:00 — FINRA + KRX 공매도
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.discovery.meme_watch.universe import build_universe
from backend.discovery.meme_watch.volume_snapshot import build_us_snapshots

logger = logging.getLogger(__name__)


def register_meme_jobs(scheduler: AsyncIOScheduler) -> None:
    """Meme Watch 잡 등록 — sector_leaders 의 listener 와 동일 시스템 공유.

    sector_leaders scheduler 의 listener 가 모든 잡 (executed/error) 이벤트를
    캐치해 logs 테이블에 module="scheduler" 로 기록함. 본 잡들도 자동 기록됨.
    """
    scheduler.add_job(
        build_universe,
        trigger=CronTrigger(
            day_of_week="sun", hour=3, minute=0, timezone="Asia/Seoul"
        ),
        id="meme_universe_weekly",
        name="매 일요일 03:00 KST — Meme Watch universe 재빌드 (US + KOSDAQ)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        build_us_snapshots,
        trigger=CronTrigger(hour=6, minute=0, timezone="Asia/Seoul"),
        id="meme_volume_us_daily",
        name="매일 06:00 KST — US Russell 2000 일봉 snapshot (volume z + RSI + 1D return)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "[meme_watch.scheduler] 2 jobs registered: "
        "meme_universe_weekly (Sun 03:00) · "
        "meme_volume_us_daily (06:00 KST)"
    )
