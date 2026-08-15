#!/usr/bin/env python3
"""sector_leaders 누락 발표월 수동 백필.

용법:
    python scripts/backfill_sector_leaders.py 2026-07 2026-08

각 발표월별로 monthly_ingest_job (motir PDF 다운·인제스트) 실행 후,
마지막으로 customs 최근 3개월 재수집 + SectorLeader 재계산.

2026-08-14 사고 (KDI catalog 2개월 갱신 누락) 백필 목적.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_sector_leaders")


def _parse_month(s: str) -> date:
    """'YYYY-MM' → date(YYYY, MM, 1)."""
    try:
        return datetime.strptime(s.strip(), "%Y-%m").date().replace(day=1)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"발표월 형식 오류 ('YYYY-MM' 필요): {s}") from e


async def backfill(report_months: list[date]) -> int:
    from backend.discovery.data_sources.motir_export.discovery import refresh_kdi_cache
    from backend.discovery.sector_leaders.scheduler import (
        _customs_fetch_recent,
        _recompute_sector_leaders,
        monthly_ingest_job,
    )
    from backend.services.db import get_session

    logger.info(f"[backfill] 대상 발표월: {[m.isoformat() for m in report_months]}")

    # 0) KDI 캐시 사전 refresh
    try:
        cache = await refresh_kdi_cache()
        logger.info(f"[backfill] KDI 캐시 갱신 완료 · {len(cache)} 건")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[backfill] KDI 캐시 갱신 실패 (시드 fallback): {e}")

    # 1) 각 발표월별 motir ingest
    failures: list[tuple[date, str]] = []
    for rm in report_months:
        logger.info(f"── {rm} motir_ingest 시작 ──")
        try:
            stats = await monthly_ingest_job(report_month=rm)
            logger.info(f"[backfill] {rm} motir ingest 완료 stats={stats}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[backfill] {rm} motir ingest 실패: {e}")
            failures.append((rm, str(e)))

    # 2) customs 최근 3개월 재수집 + 재계산 (motir 성공/실패와 독립)
    async with get_session() as session:
        try:
            cs = await _customs_fetch_recent(session, months_back=3)
            logger.info(f"[backfill] customs 재수집 완료 stats={cs}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[backfill] customs 실패: {e}")
            failures.append((None, f"customs: {e}"))
        try:
            rc = await _recompute_sector_leaders(session)
            logger.info(f"[backfill] SectorLeader 재계산 완료 stats={rc}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[backfill] recompute 실패: {e}")
            failures.append((None, f"recompute: {e}"))

    if failures:
        logger.error(f"[backfill] {len(failures)} 개 단계 실패:")
        for rm, err in failures:
            logger.error(f"  · {rm} · {err}")
        return 1
    logger.info("[backfill] 전체 완료 · 오류 없음")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="sector_leaders 누락 발표월 백필")
    parser.add_argument(
        "report_months",
        nargs="+",
        type=_parse_month,
        help="발표월 (YYYY-MM · 여러 개 가능 · 예: 2026-07 2026-08)",
    )
    args = parser.parse_args()
    return asyncio.run(backfill(args.report_months))


if __name__ == "__main__":
    sys.exit(main())
