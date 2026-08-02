"""Serenity 트윗 → serenity_signals z.ai 추출 CLI.

Phase L3 · 2026-08-02.

사용:
    python -m backend.scripts.serenity_extract --batch 10   # 10건만 (튜닝 확인)
    python -m backend.scripts.serenity_extract --batch 200  # 배치

주의:
    실 z.ai API 호출 · 비용 발생. 6222 트윗 전체 처리 전 소규모 검증 필수.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from backend.discovery.serenity.extractor import process_pending_tweets
from backend.services import config as _config  # ZAI_API_KEY .env 로드용 (side-effect import)

_ = _config  # unused-warning 회피 · load_env_once() 는 모듈 로드 시 자동 실행


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serenity 트윗 z.ai 추출")
    p.add_argument("--batch", type=int, default=50, help="1회 처리 트윗 수 (기본 50)")
    # z.ai concurrency 제한 · glm-4.5-flash=2 · glm-4.5/5.2=10 · glm-4-plus=20
    # 기본 2 = flash 안전 · flagship 모델 사용 시 CLI 로 --concurrency 상향
    p.add_argument("--concurrency", type=int, default=2, help="동시 API 호출 (기본 2 · z.ai flash rate limit)")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    result = await process_pending_tweets(
        batch_size=args.batch,
        concurrency=args.concurrency,
    )
    print(f"Serenity extract 완료: {result}")
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
