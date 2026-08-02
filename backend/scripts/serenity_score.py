"""Serenity 스코어 재계산 CLI · Phase L4 · 2026-08-02.

사용:
    python -m backend.scripts.serenity_score              # 전체 티커 (seed + active signals)
    python -m backend.scripts.serenity_score --ticker NBIS
    python -m backend.scripts.serenity_score --days 30

원리:
    - seed 있는 티커 + 최근 N일 signal 있는 티커 union
    - 각 티커 aggregate 후 15원칙 공식 재계산 · discovery_serenity_scores.total_score/auto_avoid 갱신
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from backend.discovery.serenity.scorer import (
    refresh_all_scores,
    refresh_ticker_score,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serenity 스코어 재계산")
    p.add_argument("--ticker", type=str, default=None, help="특정 티커만 갱신 (없으면 전체)")
    p.add_argument("--days", type=int, default=90, help="signal aggregate 윈도우 (기본 90)")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if args.ticker:
        result = await refresh_ticker_score(args.ticker.upper(), days=args.days)
        print(f"Serenity score ({args.ticker.upper()}): {result}")
    else:
        result = await refresh_all_scores(days=args.days)
        print(f"Serenity score 전체 재계산: {result}")
    return 0


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
