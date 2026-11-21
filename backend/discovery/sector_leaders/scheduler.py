"""Sector Leaders 매월 자동 갱신 잡 (APScheduler, B-2l 확장).

cron 3개 (모두 KST):
  ① 매월 1일 11:30  — motir PDF + customs 1~말일 + SectorLeader 재계산
  ② 매월 11일 12:00 — (motir 빠진 달 따라잡기) + customs 1~10일 + SectorLeader 재계산
  ③ 매월 21일 12:00 — (motir 빠진 달 따라잡기) + customs 1~20일 + SectorLeader 재계산

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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.customs_interim import fetch_and_save
from backend.discovery.data_sources.krx_price.loader import ingest_24m_candles
from backend.discovery.data_sources.mapping import iter_all_tickers
from backend.discovery.data_sources.motir_export.discovery import refresh_kdi_cache
from backend.discovery.data_sources.motir_export.downloader import download_kdi_pdf
from backend.discovery.sector_leaders.analysis import (
    compute_sector_leaders,
    persist_sector_leaders,
)
from backend.discovery.sector_leaders.ingest import ingest_pdf
from backend.services.db import get_session
from backend.services.models import Log, MotirItemExport

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

    # KDI num 조회는 download_kdi_pdf 내부에서 캐시 → 시드 → 실시간 크롤 3단 fallback.
    # KeyError 는 3단 모두 miss 시에만 발생 (사이트 구조 변경 등 극한 상황).
    pdf_path = await download_kdi_pdf(rm, base_dir=pdf_dir)
    async with get_session() as session:
        stats = await ingest_pdf(session, pdf_path, rm)
    logger.info(f"[motir_ingest] done report_month={rm} stats={stats}")
    return stats


# ─────────────────────────────────────────────────────────────────
# 빠진 달 따라잡기 (1120-01 · 교훈 #22)
# ─────────────────────────────────────────────────────────────────

# 한 번에 따라잡는 최대 달 수 (가장 최근 달부터 이만큼). 달마다 KDI 목록 1회 + PDF 1회 이내.
MOTIR_CATCHUP_MAX_MONTHS = 6


def _add_month(d: date, n: int = 1) -> date:
    y, m = d.year, d.month + n
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_to_catch_up(
    last_ingested: Optional[date],
    current: date,
    max_months: int = MOTIR_CATCHUP_MAX_MONTHS,
) -> list[date]:
    """마지막으로 적재한 발표월 다음 달부터 이번 달까지 (오래된 달 → 최신 달).

    - last_ingested 가 None(적재 이력 없음)이면 이번 달만.
    - 이미 이번 달까지 적재했으면 빈 목록.
    - 빠진 달이 max_months 보다 많으면 가장 최근 max_months 개만 (PDF 한 장이 13개월 시계열을 담음).
    """
    if last_ingested is None:
        return [current]
    out: list[date] = []
    m = _add_month(last_ingested, 1)
    while m <= current:
        out.append(m)
        m = _add_month(m, 1)
    return out[-max_months:]


async def _last_ingested_report_month(session: AsyncSession) -> Optional[date]:
    """DB motir_item_exports 의 source_report_month 최대값 (없으면 None)."""
    val = (
        await session.execute(select(func.max(MotirItemExport.source_report_month)))
    ).scalar_one_or_none()
    if not val:
        return None
    y, m = str(val).split("-")
    return date(int(y), int(m), 1)


async def motir_catchup(
    *,
    pdf_dir: Optional[Path] = None,
    current: Optional[date] = None,
    max_months: int = MOTIR_CATCHUP_MAX_MONTHS,
    log_tag: str = "motir_catchup",
) -> dict:
    """DB 의 마지막 발표월 다음 달부터 이번 달까지 빠진 달을 차례로 받아 적재.

    - 한 달이 실패해도 다음 달 계속.
    - 이번 달이 아직 KDI 에 없으면(KeyError) WARNING 「아직 없음」 · 지난 달이 빠졌는데 못 받으면 ERROR.
    - 반환 stats["months"][YYYY-MM] = {"status": ok|not_yet|failed, ...}.
    """
    cur = current or _first_of_current_month()
    async with get_session() as session:
        last = await _last_ingested_report_month(session)
    targets = months_to_catch_up(last, cur, max_months)
    stats: dict = {
        "last_ingested": _month_key(last) if last else None,
        "targets": [_month_key(m) for m in targets],
        "months": {},
        "ok": 0,
        "not_yet": 0,
        "failed": 0,
    }
    for rm in targets:
        key = _month_key(rm)
        is_current = rm >= cur
        try:
            stats["months"][key] = {
                "status": "ok",
                "stats": await monthly_ingest_job(report_month=rm, pdf_dir=pdf_dir),
            }
            stats["ok"] += 1
        except KeyError as e:
            if is_current:
                logger.warning(
                    f"[{log_tag}] {key} 자료가 아직 KDI 에 없음 (다음 작업에서 다시 시도): {e}"
                )
                stats["months"][key] = {"status": "not_yet", "error": str(e)}
                stats["not_yet"] += 1
            else:
                logger.error(
                    f"[{log_tag}] 지난 달 {key} 자료를 KDI 에서 못 찾음 · 빠진 채로 남음: {e}"
                )
                stats["months"][key] = {"status": "failed", "error": f"catalog_miss: {e}"}
                stats["failed"] += 1
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[{log_tag}] {key} 받기·적재 실패: {e}")
            stats["months"][key] = {"status": "failed", "error": str(e)}
            stats["failed"] += 1
    logger.info(f"[{log_tag}] done stats={stats}")
    return stats


async def _krx_candles_refresh(session: AsyncSession) -> dict:
    """매핑 51종목 × 24개월 KRX 일봉 UPSERT (pykrx).

    2026-08-15 신설 · 이전엔 초기 구축 후 갱신 크론 없어 2026-06-24 이후 방치.
    최신 월말 종가·수익률·시그널 계산에 필수.
    """
    codes = sorted({t.code for t in iter_all_tickers()})
    logger.info(f"[krx_candles_refresh] {len(codes)} 종목 24M 일봉 UPSERT 시작")
    await session.commit()  # 받기 전에 앞 단계의 열린 거래를 닫는다 (받는 동안 쓰기 잠금 없음)
    stats = await ingest_24m_candles(session, codes)  # 종목마다 commit
    await session.commit()
    if stats.get("failures", 0) > 0:
        logger.warning(f"[krx_candles_refresh] 일부 종목 실패 failures={stats['failures']} stats={stats}")
    logger.info(f"[krx_candles_refresh] done stats={stats}")
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

    # 0) KDI num 캐시 사전 refresh — 실패해도 계속 (시드 catalog fallback)
    try:
        cache = await refresh_kdi_cache()
        stats["kdi_cache_refresh"] = {"entries": len(cache), "ok": True}
        logger.info(f"[monthly_full_refresh] KDI 캐시 갱신 완료 · {len(cache)} 건")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[monthly_full_refresh] KDI 캐시 갱신 실패 · 시드 fallback: {e}")
        stats["kdi_cache_refresh"] = {"ok": False, "error": str(e)}

    # 1) motir PDF — 빠진 달 따라잡기 (report_month 를 직접 준 수동 실행은 그 달만)
    try:
        if report_month is not None:
            stats["motir"] = await monthly_ingest_job(
                report_month=report_month, pdf_dir=pdf_dir
            )
        else:
            stats["motir"] = await motir_catchup(pdf_dir=pdf_dir, log_tag="monthly_full_refresh")
    except KeyError as e:
        logger.error(f"[monthly_full_refresh] motir KDI num 3단 fallback 모두 실패: {e}")
        stats["motir"] = {"error": f"catalog_miss: {e}"}
    except Exception as e:
        logger.exception(f"[monthly_full_refresh] motir error: {e}")
        stats["motir"] = {"error": str(e)}

    # 2) customs + KRX 일봉 + recompute (motir 실패와 독립 · KRX 는 recompute 전 필수)
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=3)
        except Exception as e:
            logger.exception(f"[monthly_full_refresh] customs error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["krx_candles"] = await _krx_candles_refresh(session)
        except Exception as e:
            logger.exception(f"[monthly_full_refresh] krx_candles error: {e}")
            stats["krx_candles"] = {"error": str(e)}
        try:
            stats["recompute"] = await _recompute_sector_leaders(session)
        except Exception as e:
            logger.exception(f"[monthly_full_refresh] recompute error: {e}")
            stats["recompute"] = {"error": str(e)}

    logger.info(f"[monthly_full_refresh] done stats={stats}")
    return stats


async def customs_interim_10day_job() -> dict:
    """매월 11일 12:00 — customs 1~10일 잠정 fetch + KRX 일봉 + recompute."""
    stats: dict = {}
    # 빠진 달 따라잡기 먼저 (실패해도 나머지 단계 계속)
    try:
        stats["motir"] = await motir_catchup(log_tag="customs_10day")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[customs_10day] motir 따라잡기 error: {e}")
        stats["motir"] = {"error": str(e)}
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=2)
        except Exception as e:
            logger.exception(f"[customs_10day] error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["krx_candles"] = await _krx_candles_refresh(session)
        except Exception as e:
            logger.exception(f"[customs_10day] krx_candles error: {e}")
            stats["krx_candles"] = {"error": str(e)}
        try:
            stats["recompute"] = await _recompute_sector_leaders(session)
        except Exception as e:
            logger.exception(f"[customs_10day] recompute error: {e}")
            stats["recompute"] = {"error": str(e)}
    logger.info(f"[customs_10day] done stats={stats}")
    return stats


async def customs_interim_20day_job() -> dict:
    """매월 21일 12:00 — customs 1~20일 잠정 fetch + KRX 일봉 + recompute."""
    stats: dict = {}
    # 빠진 달 따라잡기 먼저 (실패해도 나머지 단계 계속)
    try:
        stats["motir"] = await motir_catchup(log_tag="customs_20day")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[customs_20day] motir 따라잡기 error: {e}")
        stats["motir"] = {"error": str(e)}
    async with get_session() as session:
        try:
            stats["customs"] = await _customs_fetch_recent(session, months_back=2)
        except Exception as e:
            logger.exception(f"[customs_20day] error: {e}")
            stats["customs"] = {"error": str(e)}
        try:
            stats["krx_candles"] = await _krx_candles_refresh(session)
        except Exception as e:
            logger.exception(f"[customs_20day] krx_candles error: {e}")
            stats["krx_candles"] = {"error": str(e)}
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
