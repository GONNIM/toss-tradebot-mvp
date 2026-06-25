"""산업통상부 월간 수출입동향 PDF → SQLite 적재 + cross-validation.

설계: docs/plans/sector-leaders/01-mvp-design.md

cross-validation 우선순위 (같은 (item, month) 키에 여러 발표 자료가 있을 때):
1. (장기) 확정치 자료 (is_provisional=False) 가 잠정치보다 우선.
2. 잠정치 안에서는 **데이터 월의 직후 발표** 자료가 가장 신뢰 (가장 가까운 시점).
   거리 = |발표월 - (데이터월 + 1)| 개월.
   거리가 작을수록 신뢰.
3. 모든 갱신은 MotirExportHistory 에 이전 값 기록 (감사 + cross-check).

PDF 발행 오류 (예: △ 표기 누락) 감지:
- 동일 (item, month) 키의 두 발표 자료가 다른 값이면 conflict 로 기록.
- 더 가까운 발표 자료를 신뢰하는 것이 자연스러운 보호 (PDF 발행자 오류는 보통 후속 자료에서 정정).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.motir_export import (
    parse_item_timeseries,
    parse_region_timeseries,
)
from backend.services.models import (
    MotirExportHistory,
    MotirItemExport,
    MotirRegionExport,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────


def _month_str(d: date) -> str:
    return d.strftime("%Y-%m")


def _parse_month_str(s: str) -> date:
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def _months_between(a: date, b: date) -> int:
    """|a - b| 개월."""
    return abs((a.year - b.year) * 12 + (a.month - b.month))


def _data_month_plus_one(month: date) -> date:
    """데이터 월 → 직후 발표월 (다음달 1일)."""
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _value_changed(a: float | None, b: float | None, *, tol: float = 0.5) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) > tol


def _yoy_changed(a: float | None, b: float | None, *, tol: float = 0.05) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) > tol


# ─────────────────────────────────────────────────────────────────
# 단일 PDF 적재
# ─────────────────────────────────────────────────────────────────


async def ingest_pdf(
    session: AsyncSession,
    pdf_path: Path,
    report_month: date,
) -> dict[str, int]:
    """단일 PDF → DB 적재 + cross-validation.

    Returns:
        {item_inserted, item_updated, region_inserted, region_updated,
         history_added, conflicts}
    """
    items = parse_item_timeseries(pdf_path, report_month)
    regions = parse_region_timeseries(pdf_path, report_month)

    stats = {
        "item_inserted": 0,
        "item_updated": 0,
        "region_inserted": 0,
        "region_updated": 0,
        "history_added": 0,
        "conflicts": 0,
    }
    pdf_name = pdf_path.name
    rm_str = _month_str(report_month)

    # 품목
    for r in items:
        m_str = _month_str(r.month)
        ideal_report = _data_month_plus_one(r.month)
        new_dist = _months_between(report_month, ideal_report)

        result = await session.execute(
            select(MotirItemExport).where(
                MotirItemExport.item == r.item,
                MotirItemExport.month == m_str,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            session.add(
                MotirItemExport(
                    item=r.item,
                    month=m_str,
                    value_musd=r.value_musd,
                    yoy_pct=r.yoy_pct,
                    share_pct=r.share_pct,
                    is_provisional=True,
                    source_report_month=rm_str,
                    source_pdf=pdf_name,
                )
            )
            stats["item_inserted"] += 1
            continue

        existing_rm = _parse_month_str(existing.source_report_month)
        old_dist = _months_between(existing_rm, ideal_report)

        v_chg = _value_changed(existing.value_musd, r.value_musd)
        y_chg = _yoy_changed(existing.yoy_pct, r.yoy_pct)

        if not v_chg and not y_chg:
            continue  # 변화 없음 — skip

        stats["conflicts"] += 1
        # 기존 값 history 기록
        session.add(
            MotirExportHistory(
                kind="item",
                key=r.item,
                month=m_str,
                value_musd=existing.value_musd,
                yoy_pct=existing.yoy_pct,
                share_pct=existing.share_pct,
                is_provisional=existing.is_provisional,
                source_report_month=existing.source_report_month,
            )
        )
        stats["history_added"] += 1

        if new_dist < old_dist:
            existing.value_musd = r.value_musd
            existing.yoy_pct = r.yoy_pct
            existing.share_pct = r.share_pct
            existing.source_report_month = rm_str
            existing.source_pdf = pdf_name
            stats["item_updated"] += 1
        else:
            logger.info(
                f"[cross-val] item={r.item} m={m_str}: keep existing "
                f"(existing_dist={old_dist} < new_dist={new_dist}); "
                f"new yoy={r.yoy_pct} vs existing yoy={existing.yoy_pct}"
            )

    # 지역
    for r in regions:
        m_str = _month_str(r.month)
        ideal_report = _data_month_plus_one(r.month)
        new_dist = _months_between(report_month, ideal_report)

        result = await session.execute(
            select(MotirRegionExport).where(
                MotirRegionExport.region == r.region,
                MotirRegionExport.month == m_str,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            session.add(
                MotirRegionExport(
                    region=r.region,
                    month=m_str,
                    value_musd=r.value_musd,
                    yoy_pct=r.yoy_pct,
                    is_provisional=True,
                    source_report_month=rm_str,
                    source_pdf=pdf_name,
                )
            )
            stats["region_inserted"] += 1
            continue

        existing_rm = _parse_month_str(existing.source_report_month)
        old_dist = _months_between(existing_rm, ideal_report)

        v_chg = _value_changed(existing.value_musd, r.value_musd)
        y_chg = _yoy_changed(existing.yoy_pct, r.yoy_pct)

        if not v_chg and not y_chg:
            continue

        stats["conflicts"] += 1
        session.add(
            MotirExportHistory(
                kind="region",
                key=r.region,
                month=m_str,
                value_musd=existing.value_musd,
                yoy_pct=existing.yoy_pct,
                share_pct=None,
                is_provisional=existing.is_provisional,
                source_report_month=existing.source_report_month,
            )
        )
        stats["history_added"] += 1

        if new_dist < old_dist:
            existing.value_musd = r.value_musd
            existing.yoy_pct = r.yoy_pct
            existing.source_report_month = rm_str
            existing.source_pdf = pdf_name
            stats["region_updated"] += 1

    return stats


# ─────────────────────────────────────────────────────────────────
# 디렉토리 일괄 적재
# ─────────────────────────────────────────────────────────────────


async def ingest_directory(
    session: AsyncSession,
    pdf_dir: Path,
) -> dict[str, int]:
    """디렉토리 내 모든 motir_export_*.pdf 를 데이터 월 오래된→최신 순서로 적재.

    같은 (item, month) 키에 대해 cross-validation 우선순위가 적용되어
    가장 가까운 발표 자료의 값이 최종 row 로 남는다.
    """
    pdfs: list[tuple[date, Path]] = []
    for p in pdf_dir.iterdir():
        if not p.is_file():
            continue
        if not (p.name.startswith("motir_export_") and p.name.endswith(".pdf")):
            continue
        stem = p.stem.removeprefix("motir_export_")
        try:
            y, m = stem.split("-")
            data_month = date(int(y), int(m), 1)
        except ValueError:
            logger.warning(f"파일명 파싱 실패: {p.name}")
            continue
        pdfs.append((data_month, p))

    pdfs.sort(key=lambda x: x[0])  # 오래된 데이터부터

    aggregate = {
        "item_inserted": 0,
        "item_updated": 0,
        "region_inserted": 0,
        "region_updated": 0,
        "history_added": 0,
        "conflicts": 0,
        "pdfs_processed": 0,
    }
    for data_month, pdf in pdfs:
        report_month = _data_month_plus_one(data_month)
        logger.info(
            f"[ingest] {pdf.name} (data={data_month}, report={report_month})"
        )
        stats = await ingest_pdf(session, pdf, report_month)
        for k in stats:
            aggregate[k] += stats[k]
        aggregate["pdfs_processed"] += 1

    return aggregate
