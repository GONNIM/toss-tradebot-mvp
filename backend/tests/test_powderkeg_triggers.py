"""P7-3b triggers 액션 처리 통합 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg import triggers as tr_mod
from backend.powderkeg.llm_classifier import LLMClassification
from backend.powderkeg.triggers import (
    process_event,
    process_pending_events,
    process_type_a,
    process_type_b,
)
from backend.services.db import get_session, init_db
from backend.services.models import PowderKegEvent, PowderKegList


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegEvent))
        await session.execute(delete(PowderKegList))
    yield


@pytest_asyncio.fixture(autouse=True)
async def _stub_notifier(monkeypatch):
    """모든 알림 stub · 실 telegram 호출 회피."""
    sent_log: list = []
    async def _stub(title, body, urgent=False):
        sent_log.append({"title": title, "body": body, "urgent": urgent})
        return True
    monkeypatch.setattr(tr_mod, "_send_notification", _stub)
    return sent_log


async def _seed_list(ticker: str, run_id: str = "20260715-100000"):
    async with get_session() as session:
        session.add(PowderKegList(
            run_id=run_id, ticker=ticker, status="passed",
            pbr=0.3, net_cash_ratio=0.5, owner_pct=0.4,
        ))


async def _seed_event(ticker: str, event_type: str, title: str = "테스트 이벤트") -> int:
    async with get_session() as session:
        e = PowderKegEvent(
            ticker=ticker, event_type=event_type, source="dart",
            source_id=f"id_{event_type}_{ticker}", title=title,
        )
        session.add(e)
        await session.flush()
        return e.id


@pytest.mark.asyncio
async def test_process_type_b_removes_from_list(_stub_notifier):
    await _seed_list("005930")
    eid = await _seed_event("005930", "B1", "횡령·배임 혐의발생")

    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()

    result = await process_type_b(e)
    assert result.action_taken == "list_removed"
    assert result.list_rows_removed == 1
    assert result.notification_sent is True

    # PowderKegList 에서 삭제됨
    async with get_session() as session:
        rows = (await session.execute(
            select(PowderKegList).where(PowderKegList.ticker == "005930")
        )).scalars().all()
    assert len(rows) == 0

    # 알림 · urgent
    assert _stub_notifier[0]["urgent"] is True
    assert "DO NOT TOUCH" in _stub_notifier[0]["title"]

    # 이벤트 action_taken 기록
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()
    assert e.action_taken == "list_removed"


@pytest.mark.asyncio
async def test_process_type_a_general_notifies(_stub_notifier):
    """A3 (담보제공) · 일반 알림 · 리스트 유지."""
    await _seed_list("005930")
    eid = await _seed_event("005930", "A3", "주식담보제공 계약")

    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()

    result = await process_type_a(e)
    assert result.action_taken == "notified"
    assert result.notification_sent is True
    assert _stub_notifier[0]["urgent"] is False
    assert "매수 후보" in _stub_notifier[0]["title"]

    # 리스트는 유지
    async with get_session() as session:
        rows = (await session.execute(
            select(PowderKegList).where(PowderKegList.ticker == "005930")
        )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_process_type_a1_personal_only_notifies(monkeypatch, _stub_notifier):
    """A1 · LLM 이 personal_only · 매수 후보 알림."""
    async def _stub_llm(title, description=None):
        return LLMClassification(
            label="personal_only", confidence=0.92, rationale="개인 폭행 사건",
            needs_human_review=False, used_llm=True,
        )
    monkeypatch.setattr(tr_mod, "classify_owner_event", _stub_llm)

    eid = await _seed_event("005930", "A1", "회장 개인 폭행 혐의")
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()

    result = await process_type_a(e)
    assert result.action_taken == "notified"
    assert result.llm_result is not None
    assert result.llm_result.label == "personal_only"

    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()
    assert e.confidence == pytest.approx(0.92)
    assert e.needs_human_review is False


@pytest.mark.asyncio
async def test_process_type_a1_company_related_escalates_to_b(monkeypatch, _stub_notifier):
    """A1 · LLM 이 company_related (회사자금) · Type B 로 격상 · 리스트 제거."""
    await _seed_list("005930")

    async def _stub_llm(title, description=None):
        return LLMClassification(
            label="company_related", confidence=0.90, rationale="회사 자금 관련",
            needs_human_review=False, used_llm=True,
        )
    monkeypatch.setattr(tr_mod, "classify_owner_event", _stub_llm)

    eid = await _seed_event("005930", "A1", "회장 회사자금 사용 의혹")
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()

    result = await process_type_a(e)
    assert result.action_taken == "list_removed"
    assert result.list_rows_removed == 1

    # urgent 알림
    assert _stub_notifier[0]["urgent"] is True
    assert "B 격상" in _stub_notifier[0]["title"]


@pytest.mark.asyncio
async def test_process_type_a1_low_confidence_marks_review(monkeypatch, _stub_notifier):
    """A1 · confidence < 0.8 · needs_human_review."""
    async def _stub_llm(title, description=None):
        return LLMClassification(
            label="unclear", confidence=0.6, rationale="문맥 부족",
            needs_human_review=True, used_llm=True,
        )
    monkeypatch.setattr(tr_mod, "classify_owner_event", _stub_llm)

    eid = await _seed_event("005930", "A1", "회장 사건")
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()

    result = await process_type_a(e)
    assert result.action_taken == "needs_human_review"
    assert result.notification_sent is True
    assert "사람 확인 필요" in _stub_notifier[0]["title"]

    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()
    assert e.needs_human_review is True


@pytest.mark.asyncio
async def test_process_event_dispatches_by_type(monkeypatch, _stub_notifier):
    """dispatcher · B/A/기타 분기."""
    await _seed_list("A11111")
    await _seed_list("B22222")
    eid_a = await _seed_event("A11111", "A3", "주식담보")
    eid_b = await _seed_event("B22222", "B1", "횡령")

    async with get_session() as session:
        ea = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid_a))).scalar_one()
        eb = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid_b))).scalar_one()

    ra = await process_event(ea)
    rb = await process_event(eb)
    assert ra.action_taken == "notified"
    assert rb.action_taken == "list_removed"


@pytest.mark.asyncio
async def test_process_event_skips_already_processed(monkeypatch, _stub_notifier):
    eid = await _seed_event("005930", "B1", "횡령")
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()
        e.action_taken = "list_removed"

    # 다시 처리하려 하면 skip
    async with get_session() as session:
        e = (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()
    r = await process_event(e)
    assert r.action_taken == "skip"


@pytest.mark.asyncio
async def test_process_pending_events_batch(monkeypatch, _stub_notifier):
    await _seed_list("005930")
    await _seed_list("000660")
    await _seed_event("005930", "B1", "횡령")
    await _seed_event("000660", "A3", "담보제공")

    stats = await process_pending_events()
    assert stats["total"] == 2
    assert stats["list_removed"] == 1
    assert stats["notified"] == 1