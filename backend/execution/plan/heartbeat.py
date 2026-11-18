"""하트비트 · 계획서 9절 · 9-2.

- 실행기가 30초마다 plan_executor_heartbeat 한 행을 쓴다(시각 · 웹소켓 상태 · 마지막 다시 맞추기).
- tradebot-api 가 60초마다 본다. 마지막 기록이 2분 넘게 낡으면 ⑨ 긴급 알림 1번(같은 끊김에 반복 안 함).
- 실행기 기동 · 다시 연결 → 다시 맞추기 끝 → 불변식 통과 확인 → 「실행기 복구 · 다리 n건 일치」 ⑨ 알림.
- 공개 /health 에는 「하트비트 나이(초)」 숫자 하나만 더한다(계획 · 종목 · 계좌 정보 없음).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

from sqlalchemy import select

from .models import PlanEvent, PlanExecutorHeartbeat, utcnow

_PROCESS_STARTED = utcnow()

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
        # 실행기가 한 번도 기록하지 않았다 (시작 실패 · 표 없음 · 잠금 못 잡음). 서버가 막 떠서 실행기보다 먼저 확인한 경우를 피해
        # 이 프로세스가 뜬 지 2분이 지난 뒤에만, 한 번만 알린다 (알림 1번은 사건 기록으로 막는다).
        if now - _PROCESS_STARTED <= STALE_AFTER:
            return False
        done = await s.scalar(select(PlanEvent.id).where(PlanEvent.kind == "heartbeat_none_alert").limit(1))
        if done is not None:
            return False
        s.add(PlanEvent(plan_id=None, kind="heartbeat_none_alert", ts=now, detail=""))
        await s.flush()
        await send("실행기 기록 없음", "계획 실행기가 아직 한 번도 기록을 남기지 않았습니다. 실행기가 시작되지 않았을 수 있습니다.")
        return True
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


async def _row(s) -> PlanExecutorHeartbeat:
    row = await s.get(PlanExecutorHeartbeat, 1)
    if row is None:
        row = PlanExecutorHeartbeat(id=1)
        s.add(row)
    return row


async def mark_toss(s, ok: bool, now: Optional[datetime] = None) -> None:
    """토스 호출 성공 · 실패 표시 (화면의 「토스 API 연결 · 마지막 성공 시각」)."""
    row = await _row(s)
    row.toss_status = "ok" if ok else "error"
    if ok:
        row.toss_ok_at = now or utcnow()
    await s.flush()


async def save_resync_snapshot(s, *, buying_power: Optional[float], app_conds: dict, now: Optional[datetime] = None) -> None:
    import json

    row = await _row(s)
    now = now or utcnow()
    if buying_power is not None:
        row.buying_power_usd, row.buying_power_at = float(buying_power), now
    row.app_conds_json, row.app_conds_at = json.dumps(app_conds, ensure_ascii=False), now
    await s.flush()
