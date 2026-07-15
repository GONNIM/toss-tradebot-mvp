"""공정위 공시대상기업집단 · Phase 7-1d.

지시서 §7-1-3: 연 1회 갱신 · 대기업집단 소속 플래그.

v1 구현:
    - big_biz_seed.py 의 수동 seed 리스트 사용
    - `refresh_from_seed(year)` · BigBusinessGroup 테이블 재적재
    - `is_big_biz_group(ticker, year)` · O(1) 조회
    - `resolve_group(ticker, year)` · 그룹명 반환 (또는 None)

v2 TODO:
    - 공정위 공식 자료 자동 파싱 (매년 5월 발표 · CSV 다운로드 가능하면 자동화)
    - corp_name 부분매칭 fallback (계열사 신규 편입 대응)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select

from backend.services.db import get_session
from backend.services.models import BigBusinessGroup

from .big_biz_seed import flatten_seed

logger = logging.getLogger(__name__)


async def refresh_from_seed(year: int = 2026) -> dict:
    """seed → BigBusinessGroup 테이블 재적재 (해당 year 만 delete + insert).

    Returns: {"year": ..., "deleted": N, "inserted": M}
    """
    async with get_session() as session:
        result = await session.execute(
            delete(BigBusinessGroup).where(BigBusinessGroup.year == year)
        )
        deleted = result.rowcount or 0
        inserted = 0
        for yr, group_name, ticker, corp_name in flatten_seed():
            if yr != year:
                continue
            session.add(BigBusinessGroup(
                year=year, group_name=group_name,
                corp_name=corp_name, ticker=ticker,
            ))
            inserted += 1
    stats = {"year": year, "deleted": deleted, "inserted": inserted}
    logger.info("[ftc_big_biz.seed] %s", stats)
    return stats


async def is_big_biz_group(ticker: str, year: int = 2026) -> bool:
    """지정 종목이 해당 연도 대기업집단 소속인지 여부."""
    async with get_session() as session:
        stmt = select(BigBusinessGroup.id).where(
            BigBusinessGroup.year == year,
            BigBusinessGroup.ticker == ticker,
        ).limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()
    return row is not None


async def resolve_group(ticker: str, year: int = 2026) -> Optional[str]:
    """지정 종목의 그룹명 반환."""
    async with get_session() as session:
        stmt = select(BigBusinessGroup.group_name).where(
            BigBusinessGroup.year == year,
            BigBusinessGroup.ticker == ticker,
        ).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none()


async def list_all(year: int = 2026) -> list[dict]:
    """디버그·UI용 · 전체 대기업집단 계열사 리스트."""
    async with get_session() as session:
        stmt = (
            select(BigBusinessGroup)
            .where(BigBusinessGroup.year == year)
            .order_by(BigBusinessGroup.group_name.asc(), BigBusinessGroup.ticker.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {"group_name": r.group_name, "ticker": r.ticker, "corp_name": r.corp_name}
        for r in rows
    ]
