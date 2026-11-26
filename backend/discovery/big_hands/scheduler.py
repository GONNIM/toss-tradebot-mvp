"""큰손 발자국 ② · 국내 공시 매일 수집 잡 (1119-03).

- 잡 이름: big_hands_dart_collect · 평일 19:10 KST 1회 (공시 접수 마감 18:00 뒤 · 18:00 하루 요약 · 20:30 순위 저장과 5분 이상 간격).
- 기본 꺼짐: 환경변수 BIG_HANDS_COLLECT_ENABLED=1 일 때만 등록한다. 병합 · 배포만으로 운영 DART 호출이 늘지 않게 한다.
  켜는 것은 사용자 승인 뒤에 따로 한다.
- 늦음 허용 30분(GRACE_DEFAULT) · 건너뜀 알림은 main.py 가 붙인 job_watch 감시가 맡는다 (교훈 #3).
- 실패해도 다른 잡에 번지지 않게 예외는 로그로만 남긴다. 알림 · 화면과 연결하지 않는다.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.services.job_watch import GRACE_DEFAULT

from .dart_collect import ENABLE_ENV, collect_daily, collect_enabled

logger = logging.getLogger(__name__)

JOB_ID = "big_hands_dart_collect"


async def dart_collect_job() -> dict[str, Any]:
    try:
        return await collect_daily()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] 실패 · %s", JOB_ID, exc)
        return {"error": str(exc)[:200]}


def register_big_hands_jobs(scheduler, *, force: bool = False) -> bool:
    """스위치가 꺼져 있으면 등록하지 않는다. force 는 시험이 등록 값을 보려는 용도."""
    if not (force or collect_enabled()):
        logger.info("[big_hands] 국내 공시 수집 잡 꺼짐 (%s 없음)", ENABLE_ENV)
        return False
    scheduler.add_job(
        dart_collect_job, "cron",
        day_of_week="mon-fri", hour=19, minute=10, timezone="Asia/Seoul",
        id=JOB_ID, name="큰손 발자국 국내 공시 수집", max_instances=1, coalesce=True,
        misfire_grace_time=GRACE_DEFAULT,
    )
    logger.info("[big_hands] 국내 공시 수집 잡 등록 · 평일 19:10 KST")
    return True
