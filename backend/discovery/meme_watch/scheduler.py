"""Meme Watch APScheduler 잡 등록 (Phase 1a + 1b + 1c).

잡 (모두 KST):
  ① meme_universe_weekly       — 매 일요일 03:00 — universe 재빌드
  ② meme_volume_us_daily       — 매일 06:00 — US 일봉 snapshot
  ③ meme_social_apewisdom_5min — 5분마다 — apewisdom Reddit 통합 mention

후속 Phase 에서 추가:
  ④ meme_social_reddit_5min      — Reddit PRAW (A 승인 후 활성)
  ⑤ meme_social_stocktwits_5min  — Stocktwits
  ⑥ meme_social_trends_hourly    — Google Trends
  ⑦ meme_short_daily             — FINRA + KRX 공매도
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.discovery.meme_watch.social_signal import (
    build_apewisdom_signals,
    build_reddit_signals,
)
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
    scheduler.add_job(
        build_apewisdom_signals,
        trigger=CronTrigger(minute="*/5", timezone="Asia/Seoul"),
        id="meme_social_apewisdom_5min",
        name="5분마다 — apewisdom all-stocks 상위 200 ticker mention 집계",
        replace_existing=True,
        misfire_grace_time=300,
    )
    # Reddit 직접 fetch (PRAW) 는 A 승인 후 활성. build_reddit_signals 함수는 보존.
    logger.info(
        "[meme_watch.scheduler] 3 jobs registered: "
        "meme_universe_weekly (Sun 03:00) · "
        "meme_volume_us_daily (06:00 KST) · "
        "meme_social_apewisdom_5min (every 5m)"
    )
