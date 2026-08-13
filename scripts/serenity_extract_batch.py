"""Serenity extractor 안전 수동 트리거 (2026-08-13 무한 루프 사고 후속).

⚠ z.ai 비용 발생 · while True one-liner 금지 · 반드시 이 스크립트 사용.

가드레일:
  --max-rounds N        상한 라운드 (default 5)
  --max-total-tweets N  총 z.ai 호출 상한 (default 500)
  --max-zero-rounds N   연속 signals_inserted=0 라운드 상한 (default 2)
  --dry-run             API 호출 없이 pending count 만 표시
  --batch-size N        라운드당 배치 (default 50)
  --concurrency N       동시 API 호출 (default 2 · rate limit 안전)

동작:
  1. pending count 조회
  2. dry-run 이면 예상 라운드·비용 표시 후 종료
  3. 실 실행: 라운드별 결과 stdout · 상한 도달 시 즉시 중단 (assertion)
  4. 최종 결과 요약 · pending_after=0 이 성공 지표

사용 예 (SSH · 서버):
  cd /root/toss-tradebot-mvp
  backend/.venv/bin/python scripts/serenity_extract_batch.py --dry-run
  backend/.venv/bin/python scripts/serenity_extract_batch.py --max-rounds 3
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가 (SSH 실행 컨텍스트 안전)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.services import config  # noqa: F401 · .env 로드 부수효과
from backend.discovery.serenity.extractor import (  # noqa: E402
    count_pending_tweets,
    process_pending_tweets,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--max-rounds", type=int, default=5,
                   help="라운드 상한 (default 5). 초과 시 즉시 중단.")
    p.add_argument("--max-total-tweets", type=int, default=500,
                   help="총 z.ai 호출 상한 (default 500). 비용 캡.")
    p.add_argument("--max-zero-rounds", type=int, default=2,
                   help="연속 signals_inserted=0 라운드 상한 (default 2).")
    p.add_argument("--batch-size", type=int, default=50,
                   help="라운드당 배치 크기 (default 50).")
    p.add_argument("--concurrency", type=int, default=2,
                   help="동시 z.ai 호출 수 (default 2 · rate limit 안전).")
    p.add_argument("--dry-run", action="store_true",
                   help="API 호출 없이 pending count 만 표시.")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    pending = await count_pending_tweets()
    print(f"pending tweets: {pending}")

    if args.dry_run:
        est_rounds = min(
            args.max_rounds,
            (pending + args.batch_size - 1) // args.batch_size if pending else 0,
        )
        est_calls = min(pending, est_rounds * args.batch_size)
        print(
            f"[dry-run] max_rounds={args.max_rounds} · batch_size={args.batch_size} · "
            f"예상 라운드={est_rounds} · 예상 z.ai 호출={est_calls}"
        )
        return 0

    if pending == 0:
        print("pending 0 · 실행 대상 없음.")
        return 0

    totals = {"tweets": 0, "signals_inserted": 0, "failed": 0}
    zero_streak = 0

    for round_no in range(1, args.max_rounds + 1):
        r = await process_pending_tweets(
            batch_size=args.batch_size,
            concurrency=args.concurrency,
        )
        for k in totals:
            totals[k] += r[k]
        delta = r["pending_before"] - r["pending_after"]
        print(
            f"round {round_no}: tweets={r['tweets']} signals={r['signals_inserted']} "
            f"failed={r['failed']} pending {r['pending_before']}→{r['pending_after']} "
            f"(Δ-{delta}) · running_total={totals}",
            flush=True,
        )

        # 가드 1 · pending 0 → 정상 종료
        if r["pending_after"] == 0:
            print("✅ pending 0 · 정상 종료.")
            break

        # 가드 2 · signals_inserted=0 연속 → 조기 중단 (효율 저하 감지)
        if r["signals_inserted"] == 0:
            zero_streak += 1
            if zero_streak >= args.max_zero_rounds:
                print(
                    f"⚠ signals_inserted=0 연속 {zero_streak} 라운드 · 조기 중단 "
                    "(신호 밀도 낮음 · 이후 실행 이득 미미)."
                )
                break
        else:
            zero_streak = 0

        # 가드 3 · 총 호출 상한
        if totals["tweets"] >= args.max_total_tweets:
            print(
                f"⚠ 총 처리 {totals['tweets']} ≥ {args.max_total_tweets} · 비용 캡 도달 중단."
            )
            break
    else:
        print(f"⚠ max_rounds={args.max_rounds} 도달 · 중단 (남은 pending 존재 가능).")

    remaining = await count_pending_tweets()
    print(f"FINAL: {totals} · remaining_pending={remaining}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
