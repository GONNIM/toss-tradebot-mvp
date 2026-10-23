"""하루 요약 (18:00 KST) · 오래된 기록 정리 (1022-09 Task 7 · 2026-10-23).

- 요약 모드로 쌓인 알림을 종류별 1건으로 보낸다 (gate=False·force=True — 설정·프로필 재거름 방지 · 기록은 남음).
- 보낸 종류만 대기열에서 지운다 (실패하면 다음 날 함께).
- 대기열 7일 · 발송 기록 30일이 지나면 지운다 (삭제 실패는 발송과 무관).
"""
from __future__ import annotations

import html
import logging
from collections import OrderedDict
from datetime import timedelta
from typing import Optional

from backend.services import notification_settings as ns
from backend.services.notification_log import utcnow

logger = logging.getLogger(__name__)

MAX_TITLES = 20
TITLE_CHARS = 80      # 줄당 제목 길이 · 20줄이어도 텔레그램 4096자 안
QUEUE_KEEP_DAYS = 7
LOG_KEEP_DAYS = 30


def _digest_message(category: str, titles: list[str]) -> tuple[str, str]:
    meta = ns.CATEGORIES.get(category)
    label = meta.label if meta else category
    title = f"📬 하루 요약 · {label} {len(titles)}건"
    lines = [f"오늘 하루 모아 둔 {label} 알림입니다."]
    lines += [f"· {html.escape(t if len(t) <= TITLE_CHARS else t[:TITLE_CHARS - 1] + '…')}" for t in titles[:MAX_TITLES]]
    if len(titles) > MAX_TITLES:
        lines.append(f"· 외 {len(titles) - MAX_TITLES}건")
    if meta:
        lines.append(f"자세히 보기: {ns.SITE_BASE_URL}{meta.page}")
    lines.append(f"받는 방식 바꾸기: {ns.SITE_BASE_URL}/admin/notifications")
    return title, "\n".join(lines)


async def send_daily_digest(notifier=None) -> int:
    """종류별 요약 1건씩 발송. 보낸 종류 수."""
    from sqlalchemy import delete, select

    from backend.services.db import get_session
    from backend.services.models import NotificationDigestItem
    from backend.services.notifier import Level, TelegramNotifier

    notifier = notifier or TelegramNotifier()
    async with get_session() as session:
        items = (await session.execute(select(NotificationDigestItem).order_by(NotificationDigestItem.id))).scalars().all()
    groups: "OrderedDict[str, list]" = OrderedDict()
    for it in items:
        groups.setdefault(it.category, []).append(it)

    sent = 0
    for category, rows in groups.items():
        title, body = _digest_message(category, [r.title for r in rows])
        try:
            ok = await notifier.send(Level.INFO, title, body, force=True, category=category, gate=False)
        except Exception as exc:  # noqa: BLE001 — 한 종류의 오류가 다른 종류 요약을 막지 않게
            logger.warning(f"[digest] {category} 요약 발송 오류 · 대기열 유지: {exc.__class__.__name__}")
            continue
        if not ok:
            logger.warning(f"[digest] {category} 요약 발송 실패 · 대기열 유지")
            continue
        sent += 1
        try:
            async with get_session() as session:
                await session.execute(delete(NotificationDigestItem).where(NotificationDigestItem.id.in_([r.id for r in rows])))
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[digest] {category} 보낸 요약을 대기열에서 지우지 못함 (다음 날 중복 가능): {exc.__class__.__name__}")
    return sent


async def cleanup(now: Optional[object] = None) -> dict:
    """7일 지난 대기열 · 30일 지난 발송 기록 삭제."""
    from sqlalchemy import delete

    from backend.services.db import get_session
    from backend.services.models import NotificationDigestItem, NotificationLog

    now = now or utcnow()
    async with get_session() as session:
        q = await session.execute(delete(NotificationDigestItem).where(NotificationDigestItem.created_at < now - timedelta(days=QUEUE_KEEP_DAYS)))
        lg = await session.execute(delete(NotificationLog).where(NotificationLog.created_at < now - timedelta(days=LOG_KEEP_DAYS)))
    return {"queue": q.rowcount or 0, "log": lg.rowcount or 0}


async def run_daily() -> None:
    """cron 18:00 — 요약 발송 뒤 정리 (정리 실패는 요약과 무관)."""
    n = await send_daily_digest()
    logger.info(f"[digest] 하루 요약 {n}건 발송")
    try:
        removed = await cleanup()
        logger.info(f"[digest] 정리 · 대기열 {removed['queue']} · 기록 {removed['log']}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[digest] 정리 실패 (발송과 무관): {exc.__class__.__name__}")
