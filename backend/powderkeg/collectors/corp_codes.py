"""DART corp_code 매핑 · Phase 7-1g.

DART fetch_corp_codes → DartCorpCodeMap 저장 + resolver.

- 월 1회 갱신 권장 (신규 상장·상호 변경 대응)
- 100k+ entry (상장 · 비상장 · 모두 포함)
- resolve_corp_code(ticker) · KRX 6자리 → corp_code 8자리
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.discovery.data_sources.dart.client import fetch_corp_codes
from backend.services.db import get_session
from backend.services.models import DartCorpCodeMap

logger = logging.getLogger(__name__)


async def refresh_corp_codes() -> dict:
    """DART 전체 corp_code → DartCorpCodeMap upsert.

    Returns: {"total": N, "with_stock": M, "upserted": U}
    """
    entries = await fetch_corp_codes()
    if not entries:
        return {"total": 0, "with_stock": 0, "upserted": 0, "error": "fetch_failed"}

    total = len(entries)
    with_stock = sum(1 for e in entries if e.stock_code)
    upserted = 0

    async with get_session() as session:
        for e in entries:
            existing = (await session.execute(
                select(DartCorpCodeMap).where(DartCorpCodeMap.corp_code == e.corp_code)
            )).scalar_one_or_none()
            if existing is None:
                session.add(DartCorpCodeMap(
                    corp_code=e.corp_code,
                    corp_name=e.corp_name,
                    stock_code=e.stock_code,
                    modify_date=e.modify_date,
                ))
            else:
                existing.corp_name = e.corp_name
                existing.stock_code = e.stock_code
                existing.modify_date = e.modify_date
            upserted += 1

    stats = {"total": total, "with_stock": with_stock, "upserted": upserted}
    logger.info("[powderkeg.corp_codes] refresh · %s", stats)
    return stats


async def resolve_corp_code(ticker: str) -> Optional[str]:
    """KRX 6자리 → corp_code 8자리 · 미매핑 None."""
    if not ticker:
        return None
    async with get_session() as session:
        stmt = (
            select(DartCorpCodeMap.corp_code)
            .where(DartCorpCodeMap.stock_code == ticker)
            .order_by(DartCorpCodeMap.modify_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_many(tickers: list[str]) -> dict[str, Optional[str]]:
    """다수 ticker → corp_code map."""
    if not tickers:
        return {}
    async with get_session() as session:
        stmt = select(DartCorpCodeMap.stock_code, DartCorpCodeMap.corp_code).where(
            DartCorpCodeMap.stock_code.in_(tickers)
        )
        rows = (await session.execute(stmt)).all()
    return {sc: cc for sc, cc in rows if sc}
