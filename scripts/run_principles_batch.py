#!/usr/bin/env python3
"""Principles v1.0.2 배치 CLI · 서버 수동 실행용.

용법:
    python scripts/run_principles_batch.py detect
    python scripts/run_principles_batch.py recompute
    python scripts/run_principles_batch.py all      # detect + recompute 순차

첫 배치 (2026-08-17):
    nohup python scripts/run_principles_batch.py all > /tmp/principles_batch.log 2>&1 &
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# sys.path 프로젝트 루트 (backend 모듈 import 대응)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("principles_batch")


async def run(mode: str) -> int:
    from backend.principles.scheduler import daily_recompute, weekly_detect_and_fetch

    if mode == "detect":
        stats = await weekly_detect_and_fetch()
        logger.info(f"[batch] detect done · stats={stats}")
    elif mode == "recompute":
        stats = await daily_recompute()
        logger.info(f"[batch] recompute done · stats={stats}")
    elif mode == "all":
        s1 = await weekly_detect_and_fetch()
        logger.info(f"[batch] detect done · stats={s1}")
        s2 = await daily_recompute()
        logger.info(f"[batch] recompute done · stats={s2}")
    else:
        logger.error(f"unknown mode: {mode}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Principles 배치 실행")
    parser.add_argument("mode", choices=["detect", "recompute", "all"])
    args = parser.parse_args()
    return asyncio.run(run(args.mode))


if __name__ == "__main__":
    sys.exit(main())
