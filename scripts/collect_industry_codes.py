#!/usr/bin/env python3
"""Principles v1.0.5 · 이슈 B · KSIC induty_code 일회성 수집.

용법:
    python scripts/collect_industry_codes.py [--limit N] [--force]

- KOSPI FDR 유니버스 각 종목 · DART corp_code 해결 → company.json 호출
- KSIC induty_code 저장 (principles_industry_codes)
- 이미 저장된 종목은 skip (--force 로 재수집)
- rate limit 200ms sleep
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
logger = logging.getLogger("collect_industry_codes")

DART_RATE_LIMIT_SLEEP_SEC = 0.2


async def collect(limit: int | None, force: bool) -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.discovery.data_sources.dart.client import fetch_company_info
    from backend.powderkeg.collectors.corp_codes import resolve_many
    from backend.principles.scheduler import get_kospi_universe
    from backend.services.db import get_session
    from backend.services.models import PrinciplesIndustryCode

    df = await get_kospi_universe()
    tickers = df["Code"].astype(str).tolist()
    if limit:
        tickers = tickers[:limit]

    corp_map = await resolve_many(tickers)
    logger.info(f"tickers={len(tickers)} · corp_code 매핑={len(corp_map)}")

    async with get_session() as session:
        existing = set()
        if not force:
            rows = (await session.execute(select(PrinciplesIndustryCode.ticker))).scalars().all()
            existing = set(rows)
            logger.info(f"기존 캐시={len(existing)} 종목 · skip")

        stats = {"fetched": 0, "financial": 0, "skipped": 0, "failed": 0}
        for i, ticker in enumerate(tickers):
            if ticker in existing:
                stats["skipped"] += 1
                continue
            corp_code = corp_map.get(ticker)
            if not corp_code:
                stats["skipped"] += 1
                continue
            try:
                info = await fetch_company_info(corp_code)
                stats["fetched"] += 1
                await asyncio.sleep(DART_RATE_LIMIT_SLEEP_SEC)
            except Exception as e:
                logger.warning(f"[{ticker}] fetch fail: {e}")
                stats["failed"] += 1
                continue
            if info is None:
                stats["failed"] += 1
                continue

            is_fin = info.induty_code and info.induty_code[:2] in ("64", "65", "66")
            if is_fin:
                stats["financial"] += 1

            row = PrinciplesIndustryCode(
                ticker=ticker,
                corp_code=corp_code,
                induty_code=info.induty_code,
                corp_name=info.corp_name,
            )
            merged = await session.merge(row)  # type: ignore[func-returns-value]

            if (i + 1) % 50 == 0:
                logger.info(f"progress {i+1}/{len(tickers)} · {stats}")
                await session.commit()
        await session.commit()

    logger.info(f"완료 · {stats}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Principles induty_code 수집")
    parser.add_argument("--limit", type=int, default=None, help="처음 N 종목만")
    parser.add_argument("--force", action="store_true", help="이미 저장된 종목도 재수집")
    args = parser.parse_args()
    return asyncio.run(collect(args.limit, args.force))


if __name__ == "__main__":
    sys.exit(main())
