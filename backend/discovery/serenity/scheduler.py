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

# 작업별 실행 시각 (KST) — add_job 과 실패 알림 「다음 실행」 이 같은 값을 쓴다
_JOB_SCHEDULE: dict[str, tuple[int, int]] = {
    "crawler": (6, 0),
    "extractor": (7, 0),
    "scorer": (8, 0),
    "backtest": (1, 0),
    "benchmark": (0, 30),
    "price_snapshot": (9, 30),
    "zai_cost_audit": (8, 15),
}

# 결과 키 → 한국어 (모르는 키는 그대로 · 관리용 키는 뺀다)
_RESULT_TEXT = {
    "inserted": "새로 저장", "skipped": "건너뜀", "invalid": "형식 오류", "total_archive": "전체 보관",
    "tweets": "읽은 글", "signals_inserted": "새 신호", "failed": "실패", "pending": "대기",
    "computed": "계산 끝", "delisting": "상장 폐지", "scored": "점수 매김", "snapshots": "가격 기록",
}
_RESULT_HIDDEN = {"submodule_sha"}


def _fmt_value(v) -> str:
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)


def _result_lines(result: dict) -> list[str]:
    from backend.services import alert_text as at

    known = [f"{_RESULT_TEXT[k]} {_fmt_value(v)}" for k, v in result.items() if k in _RESULT_TEXT]
    other = [f"{at.esc(k)} {at.esc(_fmt_value(v))}" for k, v in result.items()
             if k not in _RESULT_TEXT and k not in _RESULT_HIDDEN][:3]
    lines = []
    for i in range(0, len(known), 3):
        lines.append(" · ".join(known[i:i + 3]))
    return lines[:3] + other


async def _notify_job_result(job: str, result: dict | None = None, error: str | None = None) -> None:
    """크론 완료 결과 Telegram 발송 · profile 필터 존중 (문구 1023-05).

    result 예: {"pending": 500, "computed": 412, "failed": 88, "delisting": 0}
    error 시 · WARNING 레벨 발송 · 다음 실행 시각 포함.
    """
    try:
        from backend.services import alert_text as at
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        name = at.SERENITY_JOB.get(job, at.esc(job))
        if error:
            title = at.title("serenity", f"{name} 실패", "⚠️")
            lines = [f"원인: {at.esc(error)}"]
            if job in _JOB_SCHEDULE:
                lines.append(f"다음 실행: {at.next_run(*_JOB_SCHEDULE[job])}")
            lines.append(at.link("serenity"))
            await notifier.send_warning(title, "\n".join(lines), category="serenity")
        else:
            title = at.title("serenity", f"{name} 끝", _JOB_ICONS.get(job, "🔧"))
            lines = _result_lines(result) if result else []
            lines.append(at.link("serenity"))
            await notifier.send_info(title, "\n".join(lines), category="serenity")
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


# ─── 축 5 · z.ai 일일 호출 임계값 감시 (2026-08-13 사고 후속) ───────
# 정상 일일 신호 삽입 ~50 · 300 초과 시 이상 (수동 트리거 폭발·크론 이중 실행 등)

ZAI_DAILY_SIGNAL_THRESHOLD = int(os.environ.get("SERENITY_DAILY_SIGNAL_THRESHOLD", "300"))


async def _job_zai_cost_audit() -> None:
    """24h 롤링 signals_inserted 카운트 → 임계값 초과 시 Telegram 경고."""
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from backend.services.db import get_session
    from backend.services.models import SerenitySignal

    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        async with get_session() as session:
            stmt = (
                select(func.count()).select_from(SerenitySignal)
                .where(SerenitySignal.extracted_at >= cutoff)
            )
            count_24h = int((await session.execute(stmt)).scalar_one())

        logger.info("[serenity] zai_cost_audit · 24h signals=%d · threshold=%d",
                    count_24h, ZAI_DAILY_SIGNAL_THRESHOLD)

        if count_24h > ZAI_DAILY_SIGNAL_THRESHOLD:
            await _notify_job_result(
                "zai_cost_audit",
                error=(f"최근 24시간 새 신호 {count_24h}건 · 기준 {ZAI_DAILY_SIGNAL_THRESHOLD}건 넘음 · "
                       "수동 실행이나 중복 실행일 수 있음"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[serenity] cron zai_cost_audit 실패")
        await _notify_job_result("zai_cost_audit", error=str(exc)[:200])


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
        trigger=CronTrigger(hour=_JOB_SCHEDULE["crawler"][0], minute=_JOB_SCHEDULE["crawler"][1], timezone="Asia/Seoul"),
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
            trigger=CronTrigger(hour=_JOB_SCHEDULE["extractor"][0], minute=_JOB_SCHEDULE["extractor"][1], timezone="Asia/Seoul"),
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
        trigger=CronTrigger(hour=_JOB_SCHEDULE["scorer"][0], minute=_JOB_SCHEDULE["scorer"][1], timezone="Asia/Seoul"),
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
        trigger=CronTrigger(hour=_JOB_SCHEDULE["backtest"][0], minute=_JOB_SCHEDULE["backtest"][1], timezone="Asia/Seoul"),
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
        trigger=CronTrigger(hour=_JOB_SCHEDULE["benchmark"][0], minute=_JOB_SCHEDULE["benchmark"][1], timezone="Asia/Seoul"),
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
        trigger=CronTrigger(hour=_JOB_SCHEDULE["price_snapshot"][0], minute=_JOB_SCHEDULE["price_snapshot"][1], timezone="Asia/Seoul"),
        id="serenity_price_snapshot_daily",
        name="매일 09:30 KST · Serenity 언급 티커 종가 스냅샷 (yfinance)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # 축 5 · z.ai 일일 호출 임계값 감시 (2026-08-13 사고 후속)
    # 매일 08:15 KST · 24h 롤링 signals 카운트 · threshold 초과 시 Telegram alert
    scheduler.add_job(
        _job_zai_cost_audit,
        trigger=CronTrigger(hour=_JOB_SCHEDULE["zai_cost_audit"][0], minute=_JOB_SCHEDULE["zai_cost_audit"][1], timezone="Asia/Seoul"),
        id="serenity_zai_cost_audit_daily",
        name="매일 08:15 KST · Serenity z.ai 24h 신호 카운트 감시",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    logger.info("[serenity] cron 등록 완료 · 6 jobs (extractor 는 env 스위치 필요)")
