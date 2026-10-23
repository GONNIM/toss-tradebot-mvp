"""알림용 한국 종목명 읽기 조회 (1023-05 · 2026-10-23).

DB 칸 추가 없이 이미 있는 표에서 이름을 찾는다. 조회가 실패·지연돼도 알림은 그대로 나가야 하므로
예외와 시간 초과는 None 으로 돌려준다 (호출 측은 「종목명 확인 안 됨 (코드)」로 표시).
순서: 화약고 시장 스냅샷 최신 → 실주문 유니버스 → 화약고 목록 최신 → KRX 메타 (채우는 잡이 없어 마지막).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 2.0


def _session():
    from backend.services.db import get_session

    return get_session()


async def _query(ticker: str) -> Optional[str]:
    from sqlalchemy import select

    from backend.services.models import KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList

    stmts = (
        select(KrxMarketSnapshot.name)
        .where(KrxMarketSnapshot.ticker == ticker, KrxMarketSnapshot.name.is_not(None), KrxMarketSnapshot.name != "")
        .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1),
        select(LiveTapeUniverse.name).where(LiveTapeUniverse.ticker == ticker).limit(1),
        select(PowderKegList.name)
        .where(PowderKegList.ticker == ticker, PowderKegList.name.is_not(None), PowderKegList.name != "")
        .order_by(PowderKegList.run_id.desc()).limit(1),
        select(KrxStockMeta.name).where(KrxStockMeta.ticker == ticker).limit(1),
    )
    async with _session() as session:
        for stmt in stmts:
            name = (await session.execute(stmt)).scalar()
            if name:
                return name
    return None


async def lookup_kr_name(ticker: str, cache: Optional[dict[str, Optional[str]]] = None) -> Optional[str]:
    """종목 코드 → 이름. 못 찾거나 실패하면 None. cache 는 한 번 실행 안에서만 쓴다."""
    if cache is not None and ticker in cache:
        return cache[ticker]
    try:
        name = await asyncio.wait_for(_query(ticker), TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 — 시간 초과 포함 · 알림을 막지 않는다
        logger.warning(f"[stock-names] {ticker} 이름 조회 실패: {exc.__class__.__name__}")
        name = None
    if name is None:
        logger.warning(f"[stock-names] {ticker} 이름을 찾지 못함")
    if cache is not None:
        cache[ticker] = name
    return name
