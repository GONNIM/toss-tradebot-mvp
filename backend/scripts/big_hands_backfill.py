"""큰손 발자국 ② · 국내 공시 과거 채우기 일회 스크립트 (1119-03).

실행은 사용자 승인 뒤 운영 서버에서 손으로만 한다. 잡에 걸지 않고 서버 시작 때 불리지 않는다.
이 맥(로컬)에서는 실제로 돌리지 않는다 (DART 키는 서버에만 있음).

사용법 (서버 · 가상환경 안):
  python -m backend.scripts.big_hands_backfill --corp-file <회사 고유번호 목록 파일> --dry-run
  python -m backend.scripts.big_hands_backfill --corp-file <파일> --limit 20 --max-calls 400
  python -m backend.scripts.big_hands_backfill --from-corp-map --limit 20     # 지금 상장 중인 회사만 (상장폐지는 못 잡음)

  --corp-file     한 줄에 회사 고유번호(8자리) 하나. 빈 줄 · # 뒤는 무시. 저장소에 목록을 올리지 않는다.
  --from-corp-map powderkeg_dart_corp_code 표에서 종목 코드가 있는 회사 (읽기만 · 그 표는 한 달에 한 번 채워짐)
  --since         이 연도 1월 1일 이후 접수분만 저장 (기본 2016)
  --limit         이번 실행에서 새로 처리할 회사 수 상한 (기본 20)
  --max-calls     DART 호출 수 상한 (기본 500 · 하루 한도 보통 20,000)
  --batch-size    몇 회사마다 진행 줄을 남기고 쉬는지 (기본 10 · 회사마다 이미 따로 커밋됨)
  --dry-run       바깥 호출 0 · 쓰기 0. 처리할 회사 수와 호출 수 어림만 출력
  --ignore-time-window  시각 제한 무시 (시험용)

안전:
  - 처리 표시(dart_collect_cursor · 줄마다 processed_at): 다시 돌려도 끝낸 회사는 건너뛰고 같은 줄은 중복 저장하지 않는다.
  - 호출 사이 1초 이상. 한도 초과(020)나 호출 상한에 닿으면 그 자리에서 끝낸다(종료 코드 5).
  - 장 시간(평일 09:15~15:30)과 정해진 작업 시각 앞뒤에는 시작하지 않고, 실행 중 회사마다 다시 보아 걸리면 그 자리에서 끝낸다 (종료 코드 4).
  - 로그에는 개수만 남긴다. 회사 · 보고자 이름 · 키 · 응답 원문은 남기지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

EXIT_OK, EXIT_BAD_TIME, EXIT_LIMIT, EXIT_ERROR = 0, 4, 5, 6
DEFAULT_SINCE_YEAR = 2016
MIN_GAP_SEC = 1.0
# 회사당 호출 어림: elestock 1 + majorstock 1 (+ 원문은 줄 수에 따라 · 회사마다 다름)
CALLS_PER_CORP_BASE = 2

logger = logging.getLogger("big_hands_backfill")


def read_corp_file(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip()
        if t and t.isdigit() and len(t) == 8 and t not in out:
            out.append(t)
    return out


async def _corp_map_codes() -> list[str]:
    from sqlalchemy import select

    from backend.services.db import get_session
    from backend.services.models import DartCorpCodeMap

    async with get_session() as session:
        rows = (await session.execute(
            select(DartCorpCodeMap.corp_code).where(DartCorpCodeMap.stock_code.is_not(None), DartCorpCodeMap.stock_code != "")
            .order_by(DartCorpCodeMap.corp_code))).scalars().all()
    return list(rows)


async def _done_corps() -> set[str]:
    """두 종류 모두 처리 끝난 회사. 표가 아직 없으면(처음) 빈 집합."""
    from sqlalchemy import select

    from backend.discovery.big_hands.collect_models import DartCollectCursor
    from backend.services.db import get_session

    try:
        async with get_session() as session:
            rows = (await session.execute(select(
                DartCollectCursor.corp_code, DartCollectCursor.kind).where(DartCollectCursor.processed_at.is_not(None)))).all()
    except Exception:  # noqa: BLE001 · 표가 없는 처음 실행
        return set()
    kinds: dict[str, set[str]] = {}
    for corp, kind in rows:
        kinds.setdefault(corp, set()).add(kind)
    return {c for c, k in kinds.items() if {"elestock", "majorstock"} <= k}


def _in_window() -> bool:
    from backend.scripts.big_hands_probe import in_forbidden_window

    return in_forbidden_window()


async def run(
    corps: list[str], *, since_year: int, limit: int, max_calls: int, batch_size: int, dry_run: bool,
    collector=None, sleep=asyncio.sleep, check_window: bool = False,
) -> int:
    from datetime import date

    done = await _done_corps()
    pending = [c for c in corps if c not in done]
    todo = pending[:limit]
    logger.info("회사 %d · 처리 끝 %d · 남음 %d · 이번 실행 %d", len(corps), len(corps) - len(pending), len(pending), len(todo))
    logger.info("호출 어림(원문 제외) %d · 상한 %d", len(todo) * CALLS_PER_CORP_BASE, max_calls)
    if dry_run:
        logger.info("--dry-run · 바깥 호출 0 · 쓰기 0 · 끝")
        return EXIT_OK

    from backend.discovery.big_hands.dart_collect import CallLimit, CorpStats, DartCollector, RateLimited, collect_corp
    from backend.services.db import init_db

    await init_db()                       # 새 표가 없으면 만든다 (create_all · 기존 표는 건드리지 않음)
    col = collector or DartCollector(gap_sec=MIN_GAP_SEC, max_calls=max_calls)
    since = date(since_year, 1, 1)
    total, n, code = CorpStats(), 0, EXIT_OK
    for corp in todo:
        if check_window and _in_window():             # 회사마다 다시 본다 · 걸리면 그 회사를 시작하기 전에 끝낸다 (처리 표시 일관)
            logger.info("실행 제한 시각에 닿아 멈춥니다 · 끝낸 회사 %d", n)
            code = EXIT_BAD_TIME
            break
        try:
            total.add(await collect_corp(col, corp, since=since))
        except (CallLimit, RateLimited) as stop:
            logger.info("중단 · %s", type(stop).__name__)
            code = EXIT_LIMIT
            break
        n += 1
        if n % max(1, batch_size) == 0:
            logger.info("진행 %d/%d · 새 임원 줄 %d · 새 5%% 줄 %d · 원문 %d · 호출 %d",
                        n, len(todo), total.insider_new, total.major_new, total.docs_fetched, col.calls)
            await sleep(MIN_GAP_SEC)
    logger.info("끝 · 회사 %d · 새 임원 줄 %d · 새 5%% 줄 %d · 원문 받음 %d · 캐시 사용 %d · 실패 회사 %d · 호출 %d",
                n, total.insider_new, total.major_new, total.docs_fetched, total.doc_cache_hits, total.failed_corps, col.calls)
    return code


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="큰손 발자국 국내 공시 과거 채우기 (사용자 승인 뒤 서버에서 손으로)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--corp-file", type=Path)
    src.add_argument("--from-corp-map", action="store_true")
    ap.add_argument("--since", type=int, default=DEFAULT_SINCE_YEAR)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-calls", type=int, default=500)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ignore-time-window", action="store_true")
    args = ap.parse_args(argv)

    for noisy in ("httpx", "httpcore"):          # 요청 주소 줄(DART 키)이 찍히지 않게
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.dry_run and not args.ignore_time_window:
        from backend.scripts.big_hands_probe import in_forbidden_window

        if in_forbidden_window():
            logger.info("실행 제한 시각입니다 · 호출 없이 끝냅니다")
            return EXIT_BAD_TIME
    corps = asyncio.run(_corp_map_codes()) if args.from_corp_map else read_corp_file(args.corp_file)
    try:
        return asyncio.run(run(
            corps, since_year=args.since, limit=args.limit, max_calls=args.max_calls,
            batch_size=args.batch_size, dry_run=args.dry_run,
            check_window=not args.ignore_time_window))
    except Exception as exc:  # noqa: BLE001
        logger.info("중단: %s", type(exc).__name__)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
