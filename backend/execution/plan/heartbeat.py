"""하트비트 · 계획서 9절 · 9-2.

- 실행기가 30초마다 plan_executor_heartbeat 한 행을 쓴다(시각 · 웹소켓 상태 · 마지막 다시 맞추기).
- tradebot-api 가 60초마다 본다. 마지막 기록이 2분 넘게 낡으면 ⑨ 긴급 알림 1번(같은 끊김에 반복 안 함).
- 실행기 기동 · 다시 연결 → 다시 맞추기 끝 → 불변식 통과 확인 → 「실행기 복구 · 다리 n건 일치」 ⑨ 알림.
- 공개 /health 에는 「하트비트 나이(초)」 숫자 하나만 더한다(계획 · 종목 · 계좌 정보 없음).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

from .models import PlanExecutorHeartbeat, utcnow

STALE_AFTER = timedelta(minutes=2)
WRITE_EVERY_SEC = 30
CHECK_EVERY_SEC = 60

Send = Callable[[str, str], Awaitable[bool]]   # (제목, 본문) → ⑨ 긴급


async def write(s, *, ws_status: str = "none", last_resync_at: Optional[datetime] = None,
                now: Optional[datetime] = None) -> None:
    now = now or utcnow()
    row = await s.get(PlanExecutorHeartbeat, 1)
    if row is None:
        row = PlanExecutorHeartbeat(id=1)
        s.add(row)
    row.ts, row.ws_status = now, ws_status
    if last_resync_at is not None:
        row.last_resync_at = last_resync_at
    await s.flush()


async def age_seconds(s, now: Optional[datetime] = None) -> Optional[int]:
    """/health 에 더할 숫자. 기록이 한 번도 없으면 None."""
    row = await s.get(PlanExecutorHeartbeat, 1)
    if row is None:
        return None
    return max(0, int(((now or utcnow()) - row.ts).total_seconds()))


async def check_stale(s, send: Send, now: Optional[datetime] = None) -> bool:
    """2분 넘게 낡으면 ⑨ 긴급 1번. 같은 끊김에는 반복하지 않는다(알린 뒤 새 기록이 오면 다시 알릴 수 있음)."""
    now = now or utcnow()
    row = await s.get(PlanExecutorHeartbeat, 1)
    if row is None:
        return False
    if now - row.ts <= STALE_AFTER:
        return False
    if row.stale_alerted_at is not None and row.stale_alerted_at >= row.ts:
        return False
    row.stale_alerted_at = now
    await s.flush()
    secs = int((now - row.ts).total_seconds())
    await send("실행기 끊김", f"계획 실행기 기록이 {secs}초 동안 없습니다. 시간대 교대와 다리 점검이 멈췄을 수 있습니다.")
    return True


async def notify_recovered(s, send: Send, legs_matched: int, now: Optional[datetime] = None) -> bool:
    """다시 맞추기 · 불변식 통과 뒤 복구 알림 1번 (재시작마다 1번)."""
    row = await s.get(PlanExecutorHeartbeat, 1)
    if row is None:
        return False
    row.recovered_notified_at = now or utcnow()
    await s.flush()
    await send("실행기 복구", f"실행기 복구 · 다리 {legs_matched}건 일치")
    return True
