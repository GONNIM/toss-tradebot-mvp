"""Serenity backtest CLI · Phase L5 · 2026-08-02.

사용:
    python -m backend.scripts.serenity_backtest --batch 50           # 50 signals
    python -m backend.scripts.serenity_backtest --batch 1000         # 전체 (yfinance rate 유의)
    python -m backend.scripts.serenity_backtest --dry-run --batch 10 # 미리보기

주의: yfinance rate limit · 배치 100~500 권장 · 실패 signal 은 다음 실행에서 자동 재시도.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from backend.discovery.serenity.backtest import (
    backtest_signal,
    load_pending_signals,
    refresh_backtests,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serenity signals 백테스트")
    p.add_argument("--batch", type=int, default=100, help="1회 처리 signals 수 (기본 100)")
    p.add_argument("--concurrency", type=int, default=4, help="동시 yfinance 호출 (기본 4)")
    p.add_argument("--dry-run", action="store_true", help="DB write 없이 프리뷰")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _dry_run(batch: int) -> int:
    pending = await load_pending_signals(limit=batch)
    print(f"[dry-run] pending={len(pending)}")
    hits = 0
    for sig in pending[:5]:
        payload = await asyncio.to_thread(backtest_signal, sig)
        print(f"  · {sig['ticker']} @{sig['extracted_at'].date()} → {payload}")
        if payload:
            hits += 1
    print(f"[dry-run] 앞 5건 중 hits={hits}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.dry_run:
        return await _dry_run(args.batch)
    result = await refresh_backtests(
        batch_size=args.batch,
        concurrency=args.concurrency,
    )
    print(f"Serenity backtest 완료: {result}")
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
