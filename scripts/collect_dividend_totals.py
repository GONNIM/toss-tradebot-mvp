#!/usr/bin/env python3
"""Principles v1.0.5 · 이슈 C · alotMatter 재호출 + 배당총액 파싱.

용법:
    python scripts/collect_dividend_totals.py [--limit N] [--force]

- KOSPI FDR 유니버스 각 종목 · DART corp_code 해결
- 최근 5년 (Y-4 ~ Y-0) 사업보고서 alotMatter 호출
- 원시 응답 raw_json 저장 (principles_dividend_raw) · 재호출 방지
- dividend_total_krw (백만원 → 원 환산) → financial_cache.dividend_total 갱신
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("collect_dividend_totals")

DART_RATE_LIMIT_SLEEP_SEC = 0.2


async def collect(limit: int | None, force: bool) -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.powderkeg.collectors.corp_codes import resolve_many
    from backend.principles.financials import fetch_dividend_matter
    from backend.principles.scheduler import get_kospi_universe
    from backend.services.db import get_session
    from backend.services.models import (
        PrinciplesDividendRaw,
        PrinciplesFinancialCache,
    )

    df = await get_kospi_universe()
    tickers = df["Code"].astype(str).tolist()
    if limit:
        tickers = tickers[:limit]

    corp_map = await resolve_many(tickers)
    today = date.today()
    # 최근 5년 사업보고서 (당해 -5 ~ -1)
    years = [today.year - i for i in range(1, 6)]  # e.g. 2025, 2024, 2023, 2022, 2021
    logger.info(f"tickers={len(tickers)} · corp={len(corp_map)} · years={years}")

    stats = {"fetched": 0, "cached_total": 0, "skipped": 0, "failed": 0}
    async with get_session() as session:
        # 기존 raw 이력 (force=False 시 skip 판정용)
        existing_raw: set[tuple[str, int]] = set()
        if not force:
            rows = (
                await session.execute(
                    select(PrinciplesDividendRaw.corp_code, PrinciplesDividendRaw.bsns_year)
                )
            ).all()
            existing_raw = set(rows)

        for i, ticker in enumerate(tickers):
            corp_code = corp_map.get(ticker)
            if not corp_code:
                stats["skipped"] += 1
                continue
            for y in years:
                if not force and (corp_code, y) in existing_raw:
                    stats["skipped"] += 1
                    continue
                try:
                    dm = await fetch_dividend_matter(corp_code, y)
                    stats["fetched"] += 1
                    await asyncio.sleep(DART_RATE_LIMIT_SLEEP_SEC)
                except Exception as e:
                    logger.warning(f"[{ticker} {y}] fetch fail: {e}")
                    stats["failed"] += 1
                    continue
                if dm is None:
                    stats["skipped"] += 1
                    continue

                # 원시 응답 저장 (재호출 방지)
                raw_row = PrinciplesDividendRaw(
                    corp_code=corp_code,
                    bsns_year=y,
                    raw_json=json.dumps(dm.raw_rows or [], ensure_ascii=False),
                )
                await session.merge(raw_row)

                # financial_cache.dividend_total 갱신 (Q4 사업보고서 row)
                if dm.dividend_total_krw is not None:
                    stmt = (
                        select(PrinciplesFinancialCache)
                        .where(PrinciplesFinancialCache.ticker == ticker)
                        .where(PrinciplesFinancialCache.fiscal_year == y)
                        .where(PrinciplesFinancialCache.fiscal_quarter == 4)
                    )
                    fc = (await session.execute(stmt)).scalar_one_or_none()
                    if fc:
                        fc.dividend_total = dm.dividend_total_krw
                        stats["cached_total"] += 1

            if (i + 1) % 50 == 0:
                logger.info(f"progress {i+1}/{len(tickers)} · {stats}")
                await session.commit()
        await session.commit()

    logger.info(f"완료 · {stats}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="배당총액 재호출·파싱")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    return asyncio.run(collect(args.limit, args.force))


if __name__ == "__main__":
    sys.exit(main())
