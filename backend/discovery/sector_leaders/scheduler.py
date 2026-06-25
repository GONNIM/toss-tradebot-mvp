"""Sector Leaders 매월 자동 갱신 잡 (APScheduler, B-2l 확장).

cron 3개 (모두 KST):
  ① 매월 1일 11:30  — motir PDF + customs 1~말일 + SectorLeader 재계산
  ② 매월 11일 12:00 — customs 1~10일 + SectorLeader 재계산
  ③ 매월 21일 12:00 — customs 1~20일 + SectorLeader 재계산

각 단계는 try/except 로 격리 — motir KDI catalog 미등재 같은 부분 실패가
customs / recompute 진행을 막지 않음.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.customs_interim import fetch_and_save
from backend.discovery.data_sources.motir_export.downloader import (
    KDI_NUM_CATALOG,
    download_kdi_pdf,
)
from backend.discovery.sector_leaders.analysis import (
    compute_sector_leaders,
    persist_sector_leaders,
)
from backend.discovery.sector_leaders.ingest import ingest_pdf
from backend.services.db import get_session
from backend.services.models import Log

logger = logging.getLogger(__name__)

_job_start_times: dict[str, datetime] = {}


def _first_of_current_month() -> date:
    today = datetime.now()
    return date(today.year, today.month, 1)


def _shift_yymm(today: date, months_back: int) -> str:
    """today 기준 -N 개월의 YYYYMM 문자열."""
    y, m = today.year, today.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}"


# ─────────────────────────────────────────────────────────────────
# 개별 작업 단위
# ─────────────────────────────────────────────────────────────────


async def monthly_ingest_job(
    report_month: Optional[date] = None,
    *,
    pdf_dir: Optional[Path] = None,
) -> dict:
    """매월 1일 잡: motir PDF 다운로드 + ingest + cross-validation."""
    rm = report_month or _first_of_current_month()
    logger.info(f"[motir_ingest] start report_month={rm}")

    rm_key = f"{rm.year:04d}-{rm.month:02d}"
    if rm_key not in KDI_NUM_CATALOG:
        logger.error(
            f"[motir_ingest] KDI_NUM_CATALOG 에 {rm_key} 미등재 — "
            f"https://eiec.kdi.re.kr 에서 신규 num 확인 후 downloader.py 갱신 필요"
        )
        raise KeyError(f"catalog miss: {rm_key}")

    pdf_path = await download_kdi_pdf(rm, base_dir=pdf_dir)
    async with get_session() as session:
        stats = await ingest_pdf(session, pdf_path, rm)
    logger.info(f"[motir_ingest] done report_month={rm} stats={stats}")
    return stats


async def _customs_fetch_recent(
    session: AsyncSession,
    months_back: int = 3,
) -> dict:
    """최근 N개월 customs 데이터 fetch (UPSERT)."""
    today = date.today()
    end_yymm = f"{today.year:04d}{today.month:02d}"
    strt_yymm = _shift_yymm(today, months_back)
    return await fetch_and_save(session, strt_yymm=strt_yymm, end_yymm=end_yymm)


async def _recompute_sector_leaders(session: AsyncSession) -> dict:
    """SectorLeader 재계산 + persist."""
    results = await compute_sector_leaders(session)
    return await persist_sector_leaders(session, results)


# ─────────────────────────────────────────────────────────────────
# 복합 잡 — 각 단계 격리 (부분 실패 허용)
# ─────────────────────────────────────────────────────────────────


async def monthly_full_refresh_job(
    report_month: Optional[date] = None,
    pdf_dir: Optional[Path] = None,
) -> dict:
    """매월 1일 11:30 — motir + customs 최근 3개월 + sector_leaders 재계산."""
    stats: dict = {}

    # 1) motir PDF (KDI catalog 미등재 시 skip)
    try:
        stats["motir"] = await monthly_ingest_job(
            report_month=report_month, pdf_dir=pdf_dir
        )
    except KeyError as e:
        logger.warning(f"[monthly_full_refresh] motir skip: {e}")
        stats["motir"] = {"skipped": str(e)}
    except Exception as e:
        logger.exception(f"[monthly_full_refresh] motir error: {e}")
        stats["motir"] = {"error": str(e)}

    # 2) customs + recompute (motir 실패와 독립)
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=3)
        except Exception as e:
            logger.exception(f"[monthly_full_refresh] customs error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["recompute"] = await _recompute_sector_leaders(session)
        except Exception as e:
            logger.exception(f"[monthly_full_refresh] recompute error: {e}")
            stats["recompute"] = {"error": str(e)}

    logger.info(f"[monthly_full_refresh] done stats={stats}")
    return stats


async def customs_interim_10day_job() -> dict:
    """매월 11일 12:00 — customs 1~10일 잠정 fetch + recompute."""
    stats: dict = {}
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=2)
        except Exception as e:
            logger.exception(f"[customs_10day] error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["recompute"] = await _recompute_sector_leaders(session)
        except Exception as e:
            logger.exception(f"[customs_10day] recompute error: {e}")
            stats["recompute"] = {"error": str(e)}
    logger.info(f"[customs_10day] done stats={stats}")
    return stats


async def customs_interim_20day_job() -> dict:
    """매월 21일 12:00 — customs 1~20일 잠정 fetch + recompute."""
    stats: dict = {}
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=2)
        except Exception as e:
            logger.exception(f"[customs_20day] error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["recompute"] = await _recompute_sector_leaders(session)
        except Exception as e:
            logger.exception(f"[customs_20day] recompute error: {e}")
            stats["recompute"] = {"error": str(e)}
    logger.info(f"[customs_20day] done stats={stats}")
    return stats


# ─────────────────────────────────────────────────────────────────
# 잡 실행 이력 — `logs` 테이블에 module="scheduler" 로 기록
# ─────────────────────────────────────────────────────────────────


async def _persist_scheduler_log(
    level: str, message: str, context: dict
) -> None:
    try:
        async with get_session() as session:
            session.add(
                Log(
                    level=level,
                    module="scheduler",
                    message=message,
                    context=json.dumps(context, ensure_ascii=False, default=str),
                )
            )
            await session.commit()
    except Exception as e:
        logger.exception(f"[scheduler-log] persist failed: {e}")


def _on_job_submitted(event: JobSubmissionEvent) -> None:
    _job_start_times[event.job_id] = datetime.now()


def _on_job_event(event: JobExecutionEvent) -> None:
    """잡 완료/에러 → Log 테이블 기록."""
    started = _job_start_times.pop(event.job_id, None)
    duration_ms = (
        int((datetime.now() - started).total_seconds() * 1000)
        if started is not None
        else None
    )

    if event.exception is not None:
        level = "ERROR"
        message = f"[{event.job_id}] 실패: {type(event.exception).__name__}: {event.exception}"
        context = {
            "job_id": event.job_id,
            "duration_ms": duration_ms,
            "error": str(event.exception),
            "error_type": type(event.exception).__name__,
        }
    else:
        level = "INFO"
        stats = event.retval if isinstance(event.retval, dict) else {}
        message = f"[{event.job_id}] 완료"
        if duration_ms is not None:
            message += f" ({duration_ms}ms)"
        context = {
            "job_id": event.job_id,
            "duration_ms": duration_ms,
            "stats": stats,
        }

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_persist_scheduler_log(level, message, context))
    except RuntimeError:
        logger.warning(
            f"[scheduler-log] event loop not running — skip persist: {message}"
        )


# ─────────────────────────────────────────────────────────────────
# 등록
# ─────────────────────────────────────────────────────────────────


def register_monthly_jobs(scheduler: AsyncIOScheduler) -> None:
    """월간 잡 3개 등록 — 모두 KST.

    실행 시점:
      ① 매월 1일 11:30 — motir 발표 후 + customs + recompute
      ② 매월 11일 12:00 — customs 1~10일 + recompute
      ③ 매월 21일 12:00 — customs 1~20일 + recompute
    """
    scheduler.add_job(
        monthly_full_refresh_job,
        trigger=CronTrigger(day=1, hour=11, minute=30, timezone="Asia/Seoul"),
        id="monthly_full_refresh",
        name="매월 1일 — motir + customs 1~말일 + sector_leaders 재계산",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        customs_interim_10day_job,
        trigger=CronTrigger(day=11, hour=12, minute=0, timezone="Asia/Seoul"),
        id="customs_interim_10day",
        name="매월 11일 — customs 1~10일 + sector_leaders 재계산",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        customs_interim_20day_job,
        trigger=CronTrigger(day=21, hour=12, minute=0, timezone="Asia/Seoul"),
        id="customs_interim_20day",
        name="매월 21일 — customs 1~20일 + sector_leaders 재계산",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 잡 실행 이력 listener — submit / executed / error
    scheduler.add_listener(_on_job_submitted, EVENT_JOB_SUBMITTED)
    scheduler.add_listener(_on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    logger.info(
        "[scheduler] 3 jobs registered: "
        "monthly_full_refresh (1st 11:30) · "
        "customs_interim_10day (11th 12:00) · "
        "customs_interim_20day (21st 12:00) · all KST · "
        "listeners attached (submit/executed/error)"
    )
