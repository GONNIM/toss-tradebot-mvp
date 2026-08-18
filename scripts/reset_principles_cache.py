#!/usr/bin/env python3
"""Principles 캐시 완전 초기화 · 파서 fix 후 재수집 대비.

용법:
    python scripts/reset_principles_cache.py --confirm

주의: financial_cache · retry_queue · runs · results 모두 truncate.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def reset() -> int:
    from sqlalchemy import text

    from backend.services.db import get_session

    async with get_session() as session:
        for tbl in (
            "principles_financial_cache",
            "principles_dart_retry_queue",
            "principles_results",
            "principles_runs",
        ):
            r = await session.execute(text(f"DELETE FROM {tbl}"))
            print(f"cleared {tbl}: {r.rowcount} rows")
        await session.commit()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Principles 캐시 초기화")
    parser.add_argument("--confirm", action="store_true", help="필수 · 실행 확인")
    args = parser.parse_args()
    if not args.confirm:
        print("--confirm 없이는 실행하지 않습니다. 캐시 전체 삭제 확인 후 재실행.")
        return 1
    return asyncio.run(reset())


if __name__ == "__main__":
    sys.exit(main())
