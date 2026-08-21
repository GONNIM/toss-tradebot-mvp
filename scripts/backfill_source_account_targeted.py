#!/usr/bin/env python3
"""표적 백필 · sanity-INSUFFICIENT 종목 · source_account 재수집.

용법:
    python scripts/backfill_source_account_targeted.py [--tickers T1 T2 ...]
    python scripts/backfill_source_account_targeted.py  # 자동 · 최근 run INSUFFICIENT sanity

- 대상 종목의 principles_financial_cache 각 (year, quarter) 재fetch
- fetch_financial_statement 결과 파싱 → matched dict → source_account
- 저장 (net_income_owner_source_account 컬럼 갱신)
- rate 200ms · 41종목 × 평균 11분기 ~ 450 호출
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backfill_source_account")

DART_RATE_LIMIT_SLEEP_SEC = 0.2

# reprt_code 매핑 (1=Q1 · 2=반기 · 3=Q3 · 4=사업보고서)
REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}


async def backfill(tickers: list[str] | None) -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.discovery.data_sources.dart.client import fetch_financial_statement
    from backend.powderkeg.collectors.corp_codes import resolve_many
    from backend.principles.financials import parse_principles_financials
    from backend.services.db import get_session
    from backend.services.models import (
        PrinciplesFinancialCache,
        PrinciplesResult,
        PrinciplesRun,
    )

    if not tickers:
        # 자동 · 최근 run INSUFFICIENT 중 ttm_sanity reason 종목만
        async with get_session() as session:
            latest_run = (
                await session.execute(
                    select(PrinciplesRun).order_by(PrinciplesRun.id.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if not latest_run:
                logger.error("최근 run 없음")
                return 1
            rows = (
                await session.execute(
                    select(PrinciplesResult.ticker, PrinciplesResult.reasons_json)
                    .where(PrinciplesResult.run_id == latest_run.id)
                    .where(PrinciplesResult.verdict == "INSUFFICIENT_DATA")
                )
            ).all()
            tickers = []
            for t, rj in rows:
                if rj and "ttm_sanity" in rj:
                    tickers.append(t)
        logger.info(f"자동 감지 · {len(tickers)} 종목 (run #{latest_run.id})")

    corp_map = await resolve_many(tickers)
    logger.info(f"tickers={len(tickers)} · corp_code={len(corp_map)}")

    stats = {"cache_rows": 0, "dart_calls": 0, "updated": 0, "failed": 0}
    async with get_session() as session:
        for ticker in tickers:
            corp_code = corp_map.get(ticker)
            if not corp_code:
                continue
            cache_rows = (
                await session.execute(
                    select(PrinciplesFinancialCache).where(
                        PrinciplesFinancialCache.ticker == ticker
                    )
                )
            ).scalars().all()
            for row in cache_rows:
                stats["cache_rows"] += 1
                try:
                    items = await fetch_financial_statement(
                        corp_code, row.fiscal_year, REPRT[row.fiscal_quarter]
                    )
                    stats["dart_calls"] += 1
                    await asyncio.sleep(DART_RATE_LIMIT_SLEEP_SEC)
                except Exception as e:
                    logger.warning(f"[{ticker} {row.fiscal_year}Q{row.fiscal_quarter}] fetch fail: {e}")
                    stats["failed"] += 1
                    continue
                if not items:
                    continue
                parsed = parse_principles_financials(items, REPRT[row.fiscal_quarter])
                source_account = None
                if parsed.net_income_owner is not None:
                    source_account = parsed.matched.get("net_income_owner")
                elif parsed.net_income is not None:
                    source_account = parsed.matched.get("net_income")
                if source_account and source_account != row.net_income_owner_source_account:
                    row.net_income_owner_source_account = source_account
                    stats["updated"] += 1
            await session.commit()
            logger.info(f"[{ticker}] · {stats}")
    logger.info(f"완료 · {stats}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="표적 source_account 백필")
    parser.add_argument("--tickers", nargs="+", default=None)
    args = parser.parse_args()
    return asyncio.run(backfill(args.tickers))


if __name__ == "__main__":
    sys.exit(main())
