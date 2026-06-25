"""관세청 10일 잠정 수출 데이터 적재 + YoY 산출 (B-2k)."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.customs_interim.client import (
    CustomsInterimClient,
)
from backend.services.models import CustomsInterimExport

logger = logging.getLogger(__name__)


async def fetch_and_save(
    session: AsyncSession,
    strt_yymm: str,
    end_yymm: str,
    client: Optional[CustomsInterimClient] = None,
) -> dict[str, int]:
    """관세청 API 호출 → CustomsInterimExport 적재.

    같은 (month, period, country) UPSERT.
    """
    client = client or CustomsInterimClient()
    rows = await client.fetch(strt_yymm=strt_yymm, end_yymm=end_yymm)

    stats = {"fetched_rows": 0, "inserted": 0, "updated": 0}
    for row in rows:
        for amt in row.amounts:
            stats["fetched_rows"] += 1
            existing = (
                await session.execute(
                    select(CustomsInterimExport).where(
                        CustomsInterimExport.month == row.month,
                        CustomsInterimExport.period == row.period,
                        CustomsInterimExport.country_code == amt.country_code,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    CustomsInterimExport(
                        month=row.month,
                        period=row.period,
                        country_code=amt.country_code,
                        usd_amount_thousand=amt.usd_amount_thousand,
                    )
                )
                stats["inserted"] += 1
            else:
                if abs(existing.usd_amount_thousand - amt.usd_amount_thousand) > 0.5:
                    existing.usd_amount_thousand = amt.usd_amount_thousand
                    stats["updated"] += 1

    await session.commit()
    logger.info(f"[customs_ingest] {stats}")
    return stats


async def yoy_for_period(
    session: AsyncSession,
    month: str,
    period: str,
    country_code: str = "TOTAL",
) -> Optional[float]:
    """전년 동월 동기간 대비 YoY 산출."""
    if "-" not in month:
        return None
    year, mm = month.split("-")
    prev_year = str(int(year) - 1)
    prev_month = f"{prev_year}-{mm}"

    curr = (
        await session.execute(
            select(CustomsInterimExport).where(
                CustomsInterimExport.month == month,
                CustomsInterimExport.period == period,
                CustomsInterimExport.country_code == country_code,
            )
        )
    ).scalar_one_or_none()
    prev = (
        await session.execute(
            select(CustomsInterimExport).where(
                CustomsInterimExport.month == prev_month,
                CustomsInterimExport.period == period,
                CustomsInterimExport.country_code == country_code,
            )
        )
    ).scalar_one_or_none()

    if curr is None or prev is None or prev.usd_amount_thousand <= 0:
        return None
    return (curr.usd_amount_thousand / prev.usd_amount_thousand - 1) * 100.0
