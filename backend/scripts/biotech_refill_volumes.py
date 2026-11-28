"""1128-01 · 미국 바이오 후보 옛 거래량 한 번 채우기 (손으로 한 번만 실행 · 배포 때 자동으로 돌지 않음).

biotech_long_close 에 volume 열을 더한 뒤 하루 수집은 최근 1개월만 덮어쓰므로, 열을 더한 직후에는 일봉 그림의 거래량 막대가
약 20점뿐이다. 이 스크립트가 거래량이 빈 행이 있는 후보 종목만 긴 기간(6년)으로 다시 받아 빈 행의 volume 만 채운다.
야후 요청은 종목당 1번 · 종목 사이 1초 쉼. 종가 · 새 행 · 다른 표는 바꾸지 않는다.

실행은 서버 수동 실행이라 사용자 승인 뒤에만 한다 (PYTHONPATH=. 로 저장소 루트에서):
    python -m backend.scripts.biotech_refill_volumes --run
--run 이 없으면 아무것도 하지 않고 대상 종목 수만 알려 준다 (바깥 호출 0).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from backend.services import config  # noqa: F401 · biotech 스크립트 규약 (WP8 · 마스킹 필터 로드)
from backend.scripts._biotech_bootstrap import require_secure_logging

logger = logging.getLogger("biotech_refill_volumes")


async def _plan() -> dict:
    from sqlalchemy import select

    from backend.services import biotech_quotes as bq
    from backend.services.models import BiotechLongClose

    bq._require_runtime_dir()
    cands = await bq.load_candidates()
    async with bq._session() as s:
        missing = set((await s.execute(select(BiotechLongClose.ticker).where(BiotechLongClose.volume.is_(None))
                                       .distinct())).scalars().all())
    return {"candidates": len(cands), "targets": len([t for t in cands if t in missing])}


async def _main(run: bool) -> int:
    from backend.services import biotech_quotes as bq

    if not run:
        print(json.dumps(await _plan(), ensure_ascii=False))
        print("--run 을 붙이면 대상 종목을 야후에서 종목당 1번씩 다시 받습니다.")
        return 0
    res = await bq.refill_volumes()
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["failures"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    require_secure_logging()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true", help="실제로 다시 받기 (없으면 대상 수만 출력)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_main(args.run))


if __name__ == "__main__":
    sys.exit(main())
