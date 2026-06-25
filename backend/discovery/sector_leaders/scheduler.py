"""Sector Leaders 매월 자동 갱신 잡 (APScheduler).

매월 1일 11:30 KST 산업통상부 신규 발표 자료 다운로드 → ingest → cross-val.

본 모듈은 잡 정의만 제공. 등록·구동은 별도 entrypoint 에서.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.discovery.data_sources.motir_export.downloader import (
    KDI_NUM_CATALOG,
    download_kdi_pdf,
    get_pdf_path,
)
from backend.discovery.sector_leaders.ingest import ingest_pdf
from backend.services.db import get_session

logger = logging.getLogger(__name__)


def _first_of_current_month() -> date:
    today = datetime.now()
    return date(today.year, today.month, 1)


async def monthly_ingest_job(
    report_month: Optional[date] = None,
    *,
    pdf_dir: Optional[Path] = None,
) -> dict:
    """매월 1일 잡: 신규 발표 PDF 다운로드 + ingest + cross-validation.

    Args:
        report_month: 발표월. None 이면 현재 월 1일 (= 오늘 발표 자료).
        pdf_dir: PDF 저장 디렉토리 (테스트용 오버라이드).

    Returns:
        ingest 통계 dict (item_inserted, item_updated, conflicts 등).

    Raises:
        KeyError: KDI 카탈로그 미등재 (사용자가 catalog 갱신 필요)
        ValueError: 다운로드 응답이 PDF 가 아님
    """
    rm = report_month or _first_of_current_month()
    logger.info(f"[monthly_ingest_job] start report_month={rm}")

    # 카탈로그 확인 — 미등재면 명시적 에러 (사용자 액션 필요)
    rm_key = f"{rm.year:04d}-{rm.month:02d}"
    if rm_key not in KDI_NUM_CATALOG:
        logger.error(
            f"[monthly_ingest_job] KDI_NUM_CATALOG 에 {rm_key} 미등재 — "
            f"https://eiec.kdi.re.kr 에서 신규 num 확인 후 downloader.py 갱신 필요"
        )
        raise KeyError(f"catalog miss: {rm_key}")

    # 다운로드
    pdf_path = await download_kdi_pdf(rm, base_dir=pdf_dir)

    # Ingest + cross-val
    async with get_session() as session:
        stats = await ingest_pdf(session, pdf_path, rm)

    logger.info(
        f"[monthly_ingest_job] done report_month={rm} stats={stats}"
    )
    return stats


def register_monthly_jobs(scheduler: AsyncIOScheduler) -> None:
    """월간 잡을 scheduler 에 등록.

    발표 시점: 매월 1일 11:00 → 11:30 에 안전하게 다운로드 시도.
    KST timezone.
    """
    scheduler.add_job(
        monthly_ingest_job,
        trigger=CronTrigger(day=1, hour=11, minute=30, timezone="Asia/Seoul"),
        id="motir_monthly_ingest",
        name="산업통상부 월간 수출입동향 다운로드 + ingest",
        replace_existing=True,
        misfire_grace_time=3600,  # 1시간 지연까지 보정 실행
    )
    logger.info(
        "[scheduler] registered: motir_monthly_ingest (cron: 1st 11:30 KST)"
    )
