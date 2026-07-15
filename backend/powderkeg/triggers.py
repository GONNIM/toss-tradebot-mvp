"""이벤트 트리거 액션 처리 · Phase 7-3.

지시서 §7-3 완료 기준:
    - 타입 B 공시 발생 시 리스트 제거 + 알림이 5분 내 발생한다.
    - A/B 분류 로직에 대한 단위 테스트.

액션 정책:
    Type B (B1 횡령·B2 감사부적정·B3 거래정지)
        → 최신 run_id 의 PowderKegList 에서 해당 종목 제거
        → 최우선 알림 (Telegram · notifier)
        → action_taken="list_removed"

    Type A (A1~A6)
        → A1: LLM classifier 결과 반영
              · label="personal_only" → 진입 후보 알림 (needs_human_review=False)
              · label="company_related" → Type B 로 격상 · 리스트 제거
              · label="unclear" or confidence<0.8 → needs_human_review 알림
        → A2~A6: 일반 알림 (매수 후보 · 관찰)
        → action_taken="notified" / "needs_human_review" / "list_removed"

    A/B 동시 발생 시 · B 우선 (지시서 §7-3 규칙 명시).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import delete, select

from backend.services.db import get_session
from backend.services.models import PowderKegEvent, PowderKegList

from .llm_classifier import LLMClassification, classify_owner_event

logger = logging.getLogger(__name__)


# ─── notifier 얇은 wrapper · 테스트 monkeypatch 편의 ─
async def _send_notification(title: str, body: str, urgent: bool = False) -> bool:
    """알림 발송 · notifier 미설정 시 로그만."""
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        if urgent:
            await notifier.send_critical(title, body)
        else:
            await notifier.send_info(title, body)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("[powderkeg.notify] fallback log · %s · %s · %s", title, body[:120], exc)
        return False


@dataclass
class ActionResult:
    event_id: int
    action_taken: str                     # notified · list_removed · needs_human_review · skip
    list_rows_removed: int = 0
    notification_sent: bool = False
    llm_result: Optional[LLMClassification] = None


async def _remove_from_latest_list(ticker: str) -> int:
    """최신 run_id 의 PowderKegList 에서 종목 제거."""
    async with get_session() as session:
        latest_run = (await session.execute(
            select(PowderKegList.run_id)
            .order_by(PowderKegList.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if latest_run is None:
            return 0
        result = await session.execute(
            delete(PowderKegList).where(
                PowderKegList.run_id == latest_run,
                PowderKegList.ticker == ticker,
            )
        )
        return int(result.rowcount or 0)


async def _mark_event(event_id: int, action: str, llm: Optional[LLMClassification] = None) -> None:
    async with get_session() as session:
        stmt = select(PowderKegEvent).where(PowderKegEvent.id == event_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        row.action_taken = action
        if llm is not None:
            row.llm_classification = json.dumps({
                "label": llm.label,
                "confidence": llm.confidence,
                "rationale": llm.rationale,
                "used_llm": llm.used_llm,
            }, ensure_ascii=False)
            row.confidence = llm.confidence
            row.needs_human_review = llm.needs_human_review


async def process_type_b(event: PowderKegEvent) -> ActionResult:
    """Type B · 리스트 제거 + 최우선 알림."""
    removed = await _remove_from_latest_list(event.ticker)
    title = f"🚨 [DO NOT TOUCH] {event.ticker} · {event.event_type}"
    body = f"{event.title}\n원문: {event.url or 'N/A'}\n리스트에서 즉시 제거 ({removed} rows)."
    sent = await _send_notification(title, body, urgent=True)
    await _mark_event(event.id, action="list_removed")
    return ActionResult(
        event_id=event.id, action_taken="list_removed",
        list_rows_removed=removed, notification_sent=sent,
    )


async def process_type_a(event: PowderKegEvent) -> ActionResult:
    """Type A · 알림 + (A1 은 LLM 재판정)."""
    llm_result: Optional[LLMClassification] = None
    if event.event_type == "A1":
        llm_result = await classify_owner_event(event.title)
        # LLM 이 회사자금 관련이라 판정 → Type B 로 격상
        if llm_result.label == "company_related" and llm_result.confidence >= 0.8:
            removed = await _remove_from_latest_list(event.ticker)
            title = f"🚨 [B 격상] {event.ticker} · A1 → 회사자금 판정"
            body = f"{event.title}\nLLM: {llm_result.rationale} (confidence={llm_result.confidence:.2f})"
            sent = await _send_notification(title, body, urgent=True)
            await _mark_event(event.id, action="list_removed", llm=llm_result)
            return ActionResult(
                event_id=event.id, action_taken="list_removed",
                list_rows_removed=removed, notification_sent=sent,
                llm_result=llm_result,
            )
        # needs_human_review 인 경우
        if llm_result.needs_human_review:
            title = f"🟡 [사람 확인 필요] {event.ticker} · A1"
            body = f"{event.title}\nLLM confidence={llm_result.confidence:.2f} · {llm_result.rationale}"
            sent = await _send_notification(title, body, urgent=False)
            await _mark_event(event.id, action="needs_human_review", llm=llm_result)
            return ActionResult(
                event_id=event.id, action_taken="needs_human_review",
                notification_sent=sent, llm_result=llm_result,
            )
        # 확실히 personal_only · 진입 후보 알림
        title = f"🎯 [매수 후보 · A1] {event.ticker} · 오너 개인 사법"
        body = f"{event.title}\nLLM: {llm_result.rationale}"
        sent = await _send_notification(title, body, urgent=False)
        await _mark_event(event.id, action="notified", llm=llm_result)
        return ActionResult(
            event_id=event.id, action_taken="notified",
            notification_sent=sent, llm_result=llm_result,
        )

    # A2~A6 · 일반 알림
    title = f"🎯 [매수 후보 · {event.event_type}] {event.ticker}"
    body = f"{event.title}\n원문: {event.url or 'N/A'}"
    sent = await _send_notification(title, body, urgent=False)
    await _mark_event(event.id, action="notified")
    return ActionResult(
        event_id=event.id, action_taken="notified",
        notification_sent=sent,
    )


async def process_event(event: PowderKegEvent) -> ActionResult:
    """단일 이벤트 처리 · Type B 우선."""
    if event.action_taken:
        return ActionResult(event_id=event.id, action_taken="skip")
    if event.event_type.startswith("B"):
        return await process_type_b(event)
    if event.event_type.startswith("A"):
        return await process_type_a(event)
    return ActionResult(event_id=event.id, action_taken="skip")


async def process_pending_events(limit: int = 100) -> dict[str, Any]:
    """action_taken IS NULL 인 이벤트 순차 처리."""
    async with get_session() as session:
        stmt = (
            select(PowderKegEvent)
            .where(PowderKegEvent.action_taken.is_(None))
            .order_by(PowderKegEvent.detected_at.desc())
            .limit(limit)
        )
        events = (await session.execute(stmt)).scalars().all()

    stats = {"total": len(events), "notified": 0, "list_removed": 0,
             "needs_human_review": 0, "skip": 0}
    for e in events:
        r = await process_event(e)
        stats[r.action_taken] = stats.get(r.action_taken, 0) + 1
    logger.info("[powderkeg.triggers] %s", stats)
    return stats
