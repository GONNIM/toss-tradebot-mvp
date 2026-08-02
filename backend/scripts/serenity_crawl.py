"""Serenity 트윗 아카이브 → SQLite serenity_tweets sync CLI.

Phase L2 · 2026-08-02.

사용:
    python -m backend.scripts.serenity_crawl                     # 기본 경로
    SERENITY_TRACKER_DIR=/tmp/copy python -m backend.scripts.serenity_crawl
    python -m backend.scripts.serenity_crawl --tracker-dir vendor/serenity-tracker

출력 예:
    [serenity] archive 로드 · total=6222
    Serenity 트윗 sync 완료: {'inserted': 6222, 'skipped': 0, 'invalid': 0, 'total_archive': 6222}
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from backend.discovery.serenity.crawler import sync_tweets


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serenity 트윗 아카이브 sync")
    p.add_argument("--tracker-dir", type=Path, default=None,
                   help="serenity-tracker 로컬 경로 (기본: env SERENITY_TRACKER_DIR or vendor/serenity-tracker)")
    p.add_argument("--verbose", action="store_true", help="DEBUG 로그")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    result = await sync_tweets(tracker_dir=args.tracker_dir)
    print(f"Serenity 트윗 sync 완료: {result}")
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
