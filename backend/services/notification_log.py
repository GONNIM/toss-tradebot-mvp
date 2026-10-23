"""알림 발송 기록·하루 요약 대기 (1022-09 · 2026-10-23).

- 기록 쓰기 실패는 발송을 막지 않는다 (record 는 예외를 삼킨다).
- 시각은 UTC naive 로 저장한다 (SQLite CURRENT_TIMESTAMP 와 같은 기준).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _insert(row) -> None:
    from backend.services.db import get_session

    async with get_session() as session:
        session.add(row)


async def record(category: str, dedupe_key: str, title: str, result: str, error: Optional[str] = None) -> None:
    """발송 시도 1건 기록. 실패해도 예외를 올리지 않는다."""
    from backend.services.models import NotificationLog

    try:
        await _insert(NotificationLog(
            category=category, dedupe_key=dedupe_key[:200], title=title[:300],
            result=result, error=(error or None) and error[:400], created_at=utcnow(),
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[notify-log] 기록 실패 (발송과 무관): {exc.__class__.__name__}")


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
        return (await session.execute(stmt)).scalar()


async def enqueue_digest(category: str, title: str, body: str) -> None:
    """하루 요약 대기열에 넣기. 실패하면 예외를 올린다 (호출 측이 즉시 발송으로 대체)."""
    from backend.services.models import NotificationDigestItem

    await _insert(NotificationDigestItem(category=category, title=title[:300], body=body, created_at=utcnow()))
