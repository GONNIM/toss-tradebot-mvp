"""P7-5 반자동 티켓 · 무효화 조건 강제 + 상한 게이트 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.orders import (
    MAX_CONCURRENT_POSITIONS,
    MAX_TICKER_CAPITAL_PCT,
    TicketCreateRequest,
    TicketValidationError,
    approve_ticket,
    check_holding_expiry,
    create_ticket,
    mark_executed,
    reject_ticket,
)
from backend.services.db import get_session, init_db
from backend.services.models import PowderKegEvent, PowderKegOrderTicket


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegOrderTicket))
        await session.execute(delete(PowderKegEvent))
    yield


async def _seed_event(ticker: str = "005930", event_type: str = "A3", validated: bool = True) -> int:
    async with get_session() as session:
        e = PowderKegEvent(
            ticker=ticker, event_type=event_type, source="dart",
            source_id=f"id-{ticker}-{event_type}", title="테스트",
            validated=validated,
        )
        session.add(e)
        await session.flush()
        return e.id


async def _mk_request(event_id: int, ticker: str = "005930", **overrides) -> TicketCreateRequest:
    base = dict(
        event_id=event_id, ticker=ticker, proposed_qty=10,
        invalidation_price=60000.0,
        invalidation_logic="무혐의 확정 or -15% 도달",
    )
    base.update(overrides)
    return TicketCreateRequest(**base)


# ─── 정상 생성 ───────────────────────────
@pytest.mark.asyncio
async def test_create_ticket_success():
    eid = await _seed_event()
    req = await _mk_request(eid)
    ticket_id = await create_ticket(req, total_capital_krw=100_000_000, per_ticker_krw=3_000_000)
    assert ticket_id > 0

    async with get_session() as session:
        row = (await session.execute(select(PowderKegOrderTicket))).scalar_one()
    assert row.status == "pending"
    assert row.ticker == "005930"
    assert row.invalidation_price == 60000.0


# ─── 무효화 조건 게이트 ──────────────────
@pytest.mark.asyncio
async def test_missing_invalidation_price_raises():
    eid = await _seed_event()
    req = await _mk_request(eid, invalidation_price=0)
    with pytest.raises(TicketValidationError, match="invalidation_price_required"):
        await create_ticket(req, 100_000_000, 3_000_000)


@pytest.mark.asyncio
async def test_missing_invalidation_logic_raises():
    eid = await _seed_event()
    req = await _mk_request(eid, invalidation_logic="   ")
    with pytest.raises(TicketValidationError, match="invalidation_logic_required"):
        await create_ticket(req, 100_000_000, 3_000_000)


# ─── validated 게이트 ────────────────────
@pytest.mark.asyncio
async def test_not_validated_event_rejected():
    eid = await _seed_event(validated=False)
    req = await _mk_request(eid)
    with pytest.raises(TicketValidationError, match="event_not_validated"):
        await create_ticket(req, 100_000_000, 3_000_000)


@pytest.mark.asyncio
async def test_event_not_found_rejected():
    req = await _mk_request(999999)
    with pytest.raises(TicketValidationError, match="event_not_found"):
        await create_ticket(req, 100_000_000, 3_000_000)


@pytest.mark.asyncio
async def test_ticker_mismatch_rejected():
    eid = await _seed_event(ticker="005930")
    req = await _mk_request(eid, ticker="000660")   # 다른 종목
    with pytest.raises(TicketValidationError, match="ticker_mismatch"):
        await create_ticket(req, 100_000_000, 3_000_000)


# ─── 자본 상한 게이트 ────────────────────
@pytest.mark.asyncio
async def test_per_ticker_capital_over_5pct_rejected():
    eid = await _seed_event()
    req = await _mk_request(eid)
    # 자본 1억 · 티켓 600만 = 6% > 5%
    with pytest.raises(TicketValidationError, match="per_ticker_capital_over"):
        await create_ticket(req, total_capital_krw=100_000_000, per_ticker_krw=6_000_000)


@pytest.mark.asyncio
async def test_qty_zero_rejected():
    eid = await _seed_event()
    req = await _mk_request(eid, proposed_qty=0)
    with pytest.raises(TicketValidationError, match="qty_must_be_positive"):
        await create_ticket(req, 100_000_000, 3_000_000)


# ─── 동시 보유 상한 · 동일 종목 중복 ────
@pytest.mark.asyncio
async def test_duplicate_ticker_active_rejected():
    eid1 = await _seed_event(ticker="005930", event_type="A3")
    req = await _mk_request(eid1)
    await create_ticket(req, 100_000_000, 3_000_000)

    # 같은 티커 두 번째 티켓 시도
    eid2 = await _seed_event(ticker="005930", event_type="A5")
    req2 = await _mk_request(eid2)
    with pytest.raises(TicketValidationError, match="already_holding"):
        await create_ticket(req2, 100_000_000, 3_000_000)


@pytest.mark.asyncio
async def test_max_concurrent_positions_gate():
    """MAX_CONCURRENT_POSITIONS 도달 시 신규 티켓 거부."""
    # MAX 만큼 approved/executed 티켓 시딩
    async with get_session() as session:
        for i in range(MAX_CONCURRENT_POSITIONS):
            session.add(PowderKegOrderTicket(
                event_id=1, ticker=f"AA{i:04d}",
                proposed_qty=10, invalidation_price=100,
                invalidation_logic="test", status="approved",
            ))

    eid = await _seed_event(ticker="BB0000")
    req = await _mk_request(eid, ticker="BB0000")
    with pytest.raises(TicketValidationError, match="concurrent_positions_full"):
        await create_ticket(req, 100_000_000, 3_000_000)


# ─── approve / reject / execute ─────────
@pytest.mark.asyncio
async def test_approve_transitions_status():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)

    ok = await approve_ticket(tid, approver="user1")
    assert ok is True

    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == tid)
        )).scalar_one()
    assert row.status == "approved"
    assert row.approver == "user1"
    assert row.approved_at is not None


@pytest.mark.asyncio
async def test_approve_only_pending():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)
    await approve_ticket(tid, approver="u1")
    # 이미 approved → 재승인 실패
    ok = await approve_ticket(tid, approver="u2")
    assert ok is False


@pytest.mark.asyncio
async def test_reject_ticket():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)
    ok = await reject_ticket(tid, reason="사용자 판단 · 리스크 과대")
    assert ok is True
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == tid)
        )).scalar_one()
    assert row.status == "rejected"


@pytest.mark.asyncio
async def test_mark_executed_flow():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)
    await approve_ticket(tid, "u1")
    ok = await mark_executed(tid, order_uuid="uuid-abc")
    assert ok is True
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == tid)
        )).scalar_one()
    assert row.status == "executed"
    assert row.executed_order_uuid == "uuid-abc"


# ─── 보유 상한 재평가 (12개월) ────────────
@pytest.mark.asyncio
async def test_check_holding_expiry_flags_old_tickets():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)
    await approve_ticket(tid, "u1")

    # approved_at 을 400일 전으로 조작
    old_dt = datetime.now(tz=timezone.utc) - timedelta(days=400)
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == tid)
        )).scalar_one()
        row.approved_at = old_dt

    expired = await check_holding_expiry()
    assert len(expired) == 1
    assert expired[0]["ticker"] == "005930"
    assert expired[0]["age_days"] >= 365


@pytest.mark.asyncio
async def test_check_holding_expiry_ignores_fresh_tickets():
    eid = await _seed_event()
    tid = await create_ticket(await _mk_request(eid), 100_000_000, 3_000_000)
    await approve_ticket(tid, "u1")

    expired = await check_holding_expiry()
    assert len(expired) == 0
