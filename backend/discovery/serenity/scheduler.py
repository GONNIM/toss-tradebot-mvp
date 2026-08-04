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


# ─── 크론 결과 Telegram 알림 (v6 L14+ · 사용자 감시 요청 · 2026-08-04) ────

_JOB_ICONS: dict[str, str] = {
    "crawler": "📥",
    "extractor": "🧠",
    "scorer": "📊",
    "backtest": "📈",
    "price_snapshot": "💰",
    "benchmark": "🌐",
}


async def _notify_job_result(job: str, result: dict | None = None, error: str | None = None) -> None:
    """크론 완료 결과 Telegram 발송 · profile 필터 존중.

    result 예: {"pending": 500, "computed": 412, "failed": 88, "delisting": 0}
    error 시 · WARNING 레벨 발송.
    """
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        icon = _JOB_ICONS.get(job, "🔧")
        if error:
            title = f"{icon} Serenity {job} 실패"
            body = f"<code>{error}</code>"
            await notifier.send_warning(title, body)
        else:
            title = f"{icon} Serenity {job}"
            if result:
                lines = [f"<b>{k}:</b> {v}" for k, v in result.items()]
                body = "\n".join(lines)
            else:
                body = "완료"
            await notifier.send_info(title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[serenity] notifier 실패 · %s · %s", job, exc)


async def _job_crawler() -> None:
    from backend.discovery.serenity.crawler import sync_tweets
    try:
        result = await sync_tweets()
        logger.info("[serenity] cron crawler · %s", result)
        await _notify_job_result("crawler", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron crawler 실패")
        await _notify_job_result("crawler", error=str(exc)[:200])


async def _job_extractor() -> None:
    if not os.environ.get("ZAI_API_KEY"):
        logger.warning("[serenity] cron extractor skip · ZAI_API_KEY 미설정")
        return
    from backend.discovery.serenity.extractor import process_pending_tweets
    try:
        # z.ai glm-4.5-flash rate limit 2. flagship 승격 시 상향 (glm-5.2 concurrency 10).
        result = await process_pending_tweets(batch_size=200, concurrency=2)
        logger.info("[serenity] cron extractor · %s", result)
        await _notify_job_result("extractor", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron extractor 실패")
        await _notify_job_result("extractor", error=str(exc)[:200])


async def _job_scorer() -> None:
    from backend.discovery.serenity.scorer import refresh_all_scores
    try:
        result = await refresh_all_scores()
        logger.info("[serenity] cron scorer · %s", result)
        await _notify_job_result("scorer", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron scorer 실패")
        await _notify_job_result("scorer", error=str(exc)[:200])


async def _job_backtest() -> None:
    from backend.discovery.serenity.backtest import refresh_backtests
    try:
        # v6 D1: 배치 500 · Fable 5 3차 지적 반영 (주간 200 → 매일 500)
        result = await refresh_backtests(batch_size=500, concurrency=4)
        logger.info("[serenity] cron backtest · %s", result)
        await _notify_job_result("backtest", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron backtest 실패")
        await _notify_job_result("backtest", error=str(exc)[:200])


async def _job_price_snapshot() -> None:
    from backend.discovery.serenity.price_snapshot import refresh_prices
    try:
        result = await refresh_prices()
        logger.info("[serenity] cron price snapshot · %s", result)
        await _notify_job_result("price_snapshot", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron price snapshot 실패")
        await _notify_job_result("price_snapshot", error=str(exc)[:200])


async def _job_benchmark() -> None:
    from backend.discovery.serenity.benchmark import refresh_benchmark_prices
    try:
        result = await refresh_benchmark_prices()
        logger.info("[serenity] cron benchmark · %s", result)
        await _notify_job_result("benchmark", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron benchmark 실패")
        await _notify_job_result("benchmark", error=str(exc)[:200])


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

    # Phase L14 · 매일 01:00 KST · 배치 500 · Fable 5 3차 지적
    # (주 1회 × 200건 vs signals 4194건 = 21주 소요 → 매일 500건)
    scheduler.add_job(
        _job_backtest,
        trigger=CronTrigger(hour=1, minute=0, timezone="Asia/Seoul"),
        id="serenity_backtest_daily",
        name="매일 01:00 KST · Serenity yfinance 백테스트 (v6 · 배치 500)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Phase L14 · 매일 00:30 KST · IWM + SPY 400일 종가 캐시 (초과수익 산출용)
    scheduler.add_job(
        _job_benchmark,
        trigger=CronTrigger(hour=0, minute=30, timezone="Asia/Seoul"),
        id="serenity_benchmark_daily",
        name="매일 00:30 KST · Serenity IWM/SPY 벤치마크 종가 캐시",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # 티커 종가 스냅샷 (매일 09:30 KST · US 종가 이후 · vs prior close UX)
    scheduler.add_job(
        _job_price_snapshot,
        trigger=CronTrigger(hour=9, minute=30, timezone="Asia/Seoul"),
        id="serenity_price_snapshot_daily",
        name="매일 09:30 KST · Serenity 언급 티커 종가 스냅샷 (yfinance)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    logger.info("[serenity] cron 등록 완료 · 5 jobs (extractor 는 env 스위치 필요)")
