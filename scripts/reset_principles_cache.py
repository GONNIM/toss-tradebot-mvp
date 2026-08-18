#!/usr/bin/env python3
"""Principles 캐시 초기화 · 파서 fix 후 재수집 대비.

용법:
    python scripts/reset_principles_cache.py --confirm            # 기본 · 캐시만
    python scripts/reset_principles_cache.py --confirm --include-history  # 이력까지

기본 범위 (2026-08-18 조정):
  - 삭제: principles_financial_cache · principles_dart_retry_queue
  - 보존: principles_runs · principles_results (fix 전후 비교 증거)

--include-history 옵션 시 runs·results 도 삭제 (테스트·재구축용).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def reset(include_history: bool) -> int:
    from sqlalchemy import text

    from backend.services.db import get_session

    tables = ["principles_financial_cache", "principles_dart_retry_queue"]
    if include_history:
        tables += ["principles_results", "principles_runs"]

    async with get_session() as session:
        for tbl in tables:
            r = await session.execute(text(f"DELETE FROM {tbl}"))
            print(f"cleared {tbl}: {r.rowcount} rows")
        await session.commit()

    if not include_history:
        print(
            "\nnote: principles_runs · principles_results 는 보존됨 (fix 전후 비교 증거)."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Principles 캐시 초기화")
    parser.add_argument("--confirm", action="store_true", help="필수 · 실행 확인")
    parser.add_argument(
        "--include-history",
        action="store_true",
        help="선택 · runs·results 도 삭제 (기본은 보존)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="삭제 대상 목록만 출력 · 실행 안 함 (사전 검사)",
    )
    args = parser.parse_args()

    tables = ["principles_financial_cache", "principles_dart_retry_queue"]
    preserved = ["principles_runs", "principles_results"]
    if args.include_history:
        tables += preserved
        preserved = []

    print(f"삭제 대상 ({len(tables)}개):")
    for t in tables:
        print(f"  - {t}")
    if preserved:
        print(f"보존 대상 ({len(preserved)}개):")
        for t in preserved:
            print(f"  - {t}")

    if args.list:
        print("\n--list 모드 · 실행 안 함.")
        return 0
    if not args.confirm:
        print("\n--confirm 없이는 실행하지 않습니다.")
        return 1
    return asyncio.run(reset(args.include_history))


if __name__ == "__main__":
    sys.exit(main())
