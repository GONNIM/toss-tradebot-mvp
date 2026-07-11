"""KOSDAQ 유니버스 fetcher — Sprint 1 T38.

Nightly 22:00 KST refresh.
- FinanceDataReader 로 KOSDAQ 전체 종목 목록 조회
- SniperParams 필터 (시총·거래대금·주식수·가격) 적용
- 관리종목·SPAC·투자주의환기·정리매매 배제
- SQLite live_tape_universe 테이블 upsert
- Sprint 1은 오늘 Amount 로 근사 필터 · 20일 ADV 는 Sprint 1.5

계획서: docs/plans/sniper/00-sprint1-plan.md §1-3
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete

from backend.services.db import get_session
from backend.services.models import LiveTapeUniverse

from .params import SniperParams, get_sniper_params

logger = logging.getLogger(__name__)


# 배제 · Dept 문자열 매칭
_EXCLUDE_DEPT_KEYWORDS = (
    "관리종목",
    "정리매매",
    "SPAC",
    "투자주의환기",
    "투자경고",
    "투자위험",
)


def _passes_filter(row: dict, params: SniperParams) -> tuple[bool, Optional[str]]:
    """Row → (통과 여부, 배제 사유)."""
    dept = row.get("Dept") or ""
    for kw in _EXCLUDE_DEPT_KEYWORDS:
        if kw in dept:
            return False, f"dept:{kw}"

    close = row.get("Close")
    if not close or close < params.universe_price_min_krw:
        return False, f"price<{params.universe_price_min_krw:.0f}"

    marcap = row.get("Marcap")
    if not marcap:
        return False, "no_marcap"
    if marcap < params.universe_market_cap_min_krw:
        return False, f"marcap<{params.universe_market_cap_min_krw:,.0f}"
    if marcap > params.universe_market_cap_max_krw:
        return False, f"marcap>{params.universe_market_cap_max_krw:,.0f}"

    amount = row.get("Amount") or 0
    if amount < params.universe_adv_20d_min_krw:
        return False, f"amount<{params.universe_adv_20d_min_krw:,.0f}"

    stocks = row.get("Stocks") or 0
    if stocks > params.universe_float_max_shares:
        return False, f"shares>{params.universe_float_max_shares:,.0f}"

    return True, None


def _is_squeeze_candidate(row: dict, params: SniperParams) -> bool:
    stocks = row.get("Stocks") or 0
    return stocks <= params.universe_squeeze_float_max


async def refresh_universe() -> dict:
    """KOSDAQ 전체 → 필터 → live_tape_universe 테이블 upsert.

    Returns:
        {"total": N, "passed": M, "excluded": {reason: count}, "squeeze": K, "refreshed_at": iso}
    """
    import FinanceDataReader as fdr  # noqa: PLC0415

    params = get_sniper_params()
    now = datetime.now(tz=timezone.utc)

    logger.info("KOSDAQ 유니버스 fetch 시작 · fdr.StockListing")
    df = fdr.StockListing("KOSDAQ")
    total = len(df)

    passed_rows: list[dict] = []
    excluded_reasons: dict[str, int] = {}
    squeeze_count = 0

    for _, r in df.iterrows():
        row = {k: r.get(k) for k in ("Code", "Name", "Dept", "Close", "Marcap", "Stocks", "Amount")}
        ok, reason = _passes_filter(row, params)
        if not ok:
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue
        row["is_squeeze"] = _is_squeeze_candidate(row, params)
        if row["is_squeeze"]:
            squeeze_count += 1
        passed_rows.append(row)

    logger.info(
        "필터 통과 · %d/%d · squeeze 후보 %d",
        len(passed_rows), total, squeeze_count,
    )

    # DB 반영 · 이전 스냅샷 전량 대체
    async with get_session() as session:
        await session.execute(delete(LiveTapeUniverse))
        for row in passed_rows:
            entry = LiveTapeUniverse(
                ticker=row["Code"],
                name=row["Name"] or row["Code"],
                market="KOSDAQ",
                dept=row.get("Dept"),
                close_price=float(row["Close"]) if row.get("Close") else None,
                market_cap_krw=float(row["Marcap"]) if row.get("Marcap") else None,
                shares=int(row["Stocks"]) if row.get("Stocks") else None,
                amount_today=float(row["Amount"]) if row.get("Amount") else None,
                amount_20d_avg=None,        # Sprint 1.5 에서 계산
                is_squeeze_candidate=row["is_squeeze"],
                refreshed_at=now,
            )
            session.add(entry)

    stats = {
        "total": total,
        "passed": len(passed_rows),
        "squeeze": squeeze_count,
        "excluded": excluded_reasons,
        "refreshed_at": now.isoformat(),
    }
    logger.info("universe refresh 완료 · %s", stats)
    return stats


async def list_universe(*, squeeze_only: bool = False, limit: Optional[int] = None) -> list[dict]:
    """유니버스 조회 · Sniper 스캔이 참조."""
    from sqlalchemy import select

    async with get_session() as session:
        stmt = select(LiveTapeUniverse)
        if squeeze_only:
            stmt = stmt.where(LiveTapeUniverse.is_squeeze_candidate == True)  # noqa: E712
        stmt = stmt.order_by(LiveTapeUniverse.market_cap_krw.desc())
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return [
        {
            "ticker": r.ticker,
            "name": r.name,
            "close_price": r.close_price,
            "market_cap_krw": r.market_cap_krw,
            "shares": r.shares,
            "amount_today": r.amount_today,
            "is_squeeze": r.is_squeeze_candidate,
        }
        for r in rows
    ]


async def universe_size() -> int:
    from sqlalchemy import func as _func, select

    async with get_session() as session:
        result = await session.execute(select(_func.count(LiveTapeUniverse.ticker)))
        return int(result.scalar() or 0)
