"""Serenity 티커 종가 스냅샷 CLI · Phase L9 · 2026-08-03.

사용:
    python -m backend.scripts.serenity_price_snapshot                 # 언급 티커 전체
    python -m backend.scripts.serenity_price_snapshot --limit 50      # 상위 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from backend.discovery.serenity.price_snapshot import refresh_prices


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serenity 티커 종가 스냅샷")
    p.add_argument("--days", type=int, default=180, help="signal window (기본 180)")
    p.add_argument("--limit", type=int, default=None, help="상위 N 티커만")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    result = await refresh_prices(days=args.days, limit=args.limit)
    print(f"Serenity price snapshot: {result}")
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
