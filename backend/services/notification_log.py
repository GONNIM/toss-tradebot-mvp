"""알림 발송 기록·하루 요약 대기 (1022-09 · 2026-10-23 · 1119-04 고침).

- 기록 쓰기 실패는 발송을 막지 않는다 (record 는 예외를 삼킨다).
- 시각은 UTC naive 로 저장한다 (SQLite CURRENT_TIMESTAMP 와 같은 기준).

1119-04 · 쓰기 잠금과 기록 (원인: 11/19 07:15 job_plan_draft)
- 알림을 부른 쪽이 SQLite 쓰기 잠금을 쥔 채이면 새 세션 insert 가 busy_timeout 30초를 기다리고,
  그동안 부른 쪽도 멈추다가 OperationalError 로 기록이 사라졌다.
- record 는 먼저 짧게(FAST_WRITE_SECONDS) 쓴다. 잠금이 없으면 거기서 바로 써진다.
  그래서 asyncio.run(send(...)) 로 한 번 돌고 끝나는 경로의 기록은 지금처럼 남는다.
- 짧은 시도가 잠금 오류로 끝나면 모듈 대기열 하나에 넣고, 쓰기 작업 하나가 뒤에서
  2 · 10 · 30초 간격으로 다시 쓴다. 대기열 상한(QUEUE_LIMIT)을 넘으면 경고 한 줄을 남기고 버린다.
- 한계 (권고 G): 대기열은 메모리에만 있다. 잠금이 풀리기 전에 프로세스가 끝나거나 다시 뜨면
  (배포 재시작 · asyncio.run 이 끝나는 경로에서 잠금이 계속된 경우) 남은 기록은 사라진다.
  아직 쓰지 못한 sent · queued 기록은 last_activity_at 이 함께 봐서 같은 프로세스 안의
  재발송 간격 판정은 틀리지 않는다 (다른 프로세스는 모른다).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

FAST_WRITE_SECONDS = 1.5          # 짧은 시도에서 잠금을 기다리는 최대 시간
RETRY_DELAYS = (2, 10, 30)        # 뒤에서 다시 쓰는 간격 (초) · 세 번 다 실패하면 경고 후 버림
QUEUE_LIMIT = 500                 # 대기열 상한
_BUSY_DEFAULT_MS = 30000          # db.py 의 PRAGMA busy_timeout 과 같은 값 (짧은 시도 뒤 되돌림)

_queue: "deque[_Pending]" = deque()
_worker: Optional["asyncio.Task"] = None


class _Pending:
    __slots__ = ("fields",)

    def __init__(self, fields: dict) -> None:
        self.fields = fields


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _insert(row, busy_ms: Optional[int] = None) -> None:
    """row 1건 저장. busy_ms 가 있으면 이 연결에만 잠금 대기를 그만큼으로 줄인다 (SQLite).

    짧은 제한을 asyncio.wait_for 로 걸지 않은 까닭: 취소해도 aiosqlite 스레드는 30초 대기를
    계속하고 뒤늦게 써 버려 다시 쓰기와 겹쳐 중복될 수 있다. 연결 단위 busy_timeout 은
    SQLite 가 그 시간에 직접 포기하므로 중복이 없다. 쓰고 나면 30초로 되돌려 풀에 돌려준다.
    """
    from sqlalchemy import text

    from backend.services import db

    if busy_ms is None:
        async with db.get_session() as session:
            session.add(row)
        return
    async with db.AsyncSessionLocal() as session:
        sqlite = session.get_bind().dialect.name == "sqlite"
        try:
            if sqlite:
                await session.execute(text(f"PRAGMA busy_timeout={int(busy_ms)}"))
            session.add(row)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if sqlite:
                try:
                    await session.execute(text(f"PRAGMA busy_timeout={_BUSY_DEFAULT_MS}"))
                except Exception:  # noqa: BLE001
                    pass


def _make_row(fields: dict):
    from backend.services.models import NotificationLog

    return NotificationLog(**fields)


async def _try_write(item: _Pending) -> None:
    await _insert(_make_row(item.fields), busy_ms=int(FAST_WRITE_SECONDS * 1000))


def _drop(item: _Pending) -> None:
    try:
        _queue.remove(item)
    except ValueError:
        pass


async def _drain() -> None:
    """대기열 앞에서부터 하나씩 다시 쓴다 (쓰기 작업은 하나 · 순서 유지)."""
    while _queue:
        item = _queue[0]
        for delay in RETRY_DELAYS:
            await asyncio.sleep(delay)
            try:
                await _try_write(item)
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        else:
            logger.warning(f"[notify-log] 기록 실패 (발송과 무관): {last.__class__.__name__}")
        _drop(item)


def _ensure_worker() -> None:
    global _worker
    loop = asyncio.get_running_loop()
    if _worker is not None and not _worker.done() and _worker.get_loop() is loop:
        return
    _worker = loop.create_task(_drain())


async def record(category: str, dedupe_key: str, title: str, result: str, error: Optional[str] = None) -> None:
    """발송 시도 1건 기록. 실패해도 예외를 올리지 않는다.

    짧게 먼저 쓰고, 잠금이면 대기열로 넘겨 바로 돌아온다 (created_at 은 부른 시각).
    """
    item = _Pending(dict(
        category=category, dedupe_key=dedupe_key[:200], title=title[:300],
        result=result, error=(error or None) and error[:400], created_at=utcnow(),
    ))
    try:
        await _try_write(item)
        return
    except Exception as exc:  # noqa: BLE001
        from sqlalchemy.exc import OperationalError

        if not isinstance(exc, OperationalError):
            logger.warning(f"[notify-log] 기록 실패 (발송과 무관): {exc.__class__.__name__}")
            return
    if len(_queue) >= QUEUE_LIMIT:
        logger.warning(f"[notify-log] 대기열 가득 참 ({QUEUE_LIMIT}건) · 기록 버림")
        return
    _queue.append(item)
    _ensure_worker()


async def flush_pending() -> int:
    """대기 중인 기록을 지금 한 번씩 써 본다 (시험 · 종료 전용). 아직 못 쓴 건수를 돌려준다."""
    global _worker
    if _worker is not None and not _worker.done():
        _worker.cancel()
        try:
            await _worker
        except BaseException:  # noqa: BLE001 — 취소 또는 다른 루프
            pass
    _worker = None
    for item in list(_queue):
        try:
            await _try_write(item)
            _drop(item)
        except Exception:  # noqa: BLE001
            pass
    return len(_queue)


def pending_count() -> int:
    return len(_queue)


def reset_pending() -> None:
    """시험용 · 대기열과 쓰기 작업 참조를 비운다."""
    global _worker
    if _worker is not None and not _worker.done():
        try:
            _worker.cancel()
        except Exception:  # noqa: BLE001
            pass
    _worker = None
    _queue.clear()


async def last_activity_at(category: str, dedupe_key: str) -> Optional[datetime]:
    """같은 종류·식별자의 마지막 sent 또는 queued 시각 (재발송 간격 판정)."""
    from sqlalchemy import func, select

    from backend.services.db import get_session
    from backend.services.models import NotificationLog

    async with get_session() as session:
        stmt = select(func.max(NotificationLog.created_at)).where(
            NotificationLog.category == category,
            NotificationLog.dedupe_key == dedupe_key[:200],
            NotificationLog.result.in_(("sent", "queued")),
        )
        db_last = (await session.execute(stmt)).scalar()
    # 1119-04 · 아직 DB 에 못 쓴 sent · queued 기록도 함께 본다 (권고 D)
    mem = [p.fields["created_at"] for p in _queue
           if p.fields["category"] == category and p.fields["dedupe_key"] == dedupe_key[:200]
           and p.fields["result"] in ("sent", "queued")]
    cands = [t for t in (db_last, *mem) if t is not None]
    return max(cands) if cands else None


async def enqueue_digest(category: str, title: str, body: str) -> None:
    """하루 요약 대기열에 넣기. 실패하면 예외를 올린다 (호출 측이 즉시 발송으로 대체)."""
    from backend.services.models import NotificationDigestItem

    await _insert(NotificationDigestItem(category=category, title=title[:300], body=body, created_at=utcnow()))
