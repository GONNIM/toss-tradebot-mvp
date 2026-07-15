"""P7-6a Powder Keg API 통합 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["SNIPER_API_TOKEN"] = "test_token_32chars_00000000000000"

from backend.services.db import get_session, init_db
from backend.services.models import (
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
)


TOKEN = "test_token_32chars_00000000000000"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegList))
        await session.execute(delete(PowderKegEvent))
        await session.execute(delete(PowderKegOrderTicket))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_disclaimer_returned(client):
    r = await client.get("/api/v1/powderkeg/disclaimer")
    assert r.status_code == 200
    assert "투자 권유가 아닙니다" in r.json()["disclaimer"]


@pytest.mark.asyncio
async def test_list_empty(client):
    r = await client.get("/api/v1/powderkeg/list")
    body = r.json()
    assert body["items"] == []
    assert "disclaimer" in body


@pytest.mark.asyncio
async def test_list_returns_latest_run(client):
    async with get_session() as session:
        session.add(PowderKegList(
            run_id="20260715-100000", ticker="005930", name="삼성전자",
            status="passed", pbr=0.4, net_cash_ratio=0.55, piotroski_f_score=7,
        ))
        session.add(PowderKegList(
            run_id="20260715-100000", ticker="000660", name="SK하이닉스",
            status="rejected", pbr=1.2, net_cash_ratio=0.10,
            reject_reasons="pbr>=0.5",
        ))
    r = await client.get("/api/v1/powderkeg/list")
    body = r.json()
    assert body["run_id"] == "20260715-100000"
    assert body["count"] == 2
    # net_cash_ratio 내림차순 (passed 먼저)
    assert body["items"][0]["ticker"] == "005930"


@pytest.mark.asyncio
async def test_list_status_filter(client):
    async with get_session() as session:
        session.add(PowderKegList(run_id="R1", ticker="A", name="A", status="passed",
                                  pbr=0.3, net_cash_ratio=0.5))
        session.add(PowderKegList(run_id="R1", ticker="B", name="B", status="rejected",
                                  pbr=1.0, net_cash_ratio=0.1))
    r = await client.get("/api/v1/powderkeg/list?status=passed")
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["ticker"] == "A"


@pytest.mark.asyncio
async def test_events_shows_recent_with_a_b_kind(client):
    async with get_session() as session:
        session.add(PowderKegEvent(
            ticker="005930", event_type="A3", source="dart",
            source_id="d1", title="주식담보제공 계약",
            url="https://dart.fss.or.kr/main?rcpNo=1",
        ))
        session.add(PowderKegEvent(
            ticker="000660", event_type="B1", source="dart",
            source_id="d2", title="횡령·배임 혐의발생",
            url="https://dart.fss.or.kr/main?rcpNo=2",
        ))
    r = await client.get("/api/v1/powderkeg/events")
    body = r.json()
    assert body["count"] == 2
    kinds = {i["kind"] for i in body["items"]}
    assert kinds == {"A", "B"}
    # 원문 링크 유지 · 판단 문구 없음
    for i in body["items"]:
        assert i["url"].startswith("https://dart.fss.or.kr")


@pytest.mark.asyncio
async def test_tickets_list(client):
    async with get_session() as session:
        session.add(PowderKegOrderTicket(
            event_id=1, ticker="005930",
            proposed_qty=10, invalidation_price=60000.0,
            invalidation_logic="테스트", status="pending",
        ))
    r = await client.get("/api/v1/powderkeg/tickets")
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_screener_requires_token(client):
    r = await client.post("/api/v1/powderkeg/screener/run",
                          json={"tickers": ["005930"]})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_screener_run_with_token(client):
    r = await client.post(
        "/api/v1/powderkeg/screener/run",
        headers={"X-API-Token": TOKEN},
        json={"tickers": ["005930"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_ticket_create_and_approve(client):
    # 우선 validated event 시딩
    async with get_session() as session:
        e = PowderKegEvent(
            ticker="005930", event_type="A3", source="dart",
            source_id="d1", title="담보", validated=True,
        )
        session.add(e)
        await session.flush()
        eid = e.id

    r = await client.post(
        "/api/v1/powderkeg/ticket",
        headers={"X-API-Token": TOKEN},
        json={
            "event_id": eid, "ticker": "005930", "proposed_qty": 10,
            "invalidation_price": 60000.0,
            "invalidation_logic": "무혐의 확정",
            "total_capital_krw": 100_000_000,
            "per_ticker_krw": 3_000_000,
        },
    )
    assert r.status_code == 200
    tid = r.json()["id"]

    # approve
    r = await client.patch(
        f"/api/v1/powderkeg/ticket/{tid}/approve",
        headers={"X-API-Token": TOKEN},
        json={"approver": "user1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_ticket_create_missing_invalidation_rejected(client):
    async with get_session() as session:
        e = PowderKegEvent(
            ticker="005930", event_type="A3", source="dart",
            source_id="d1", title="담보", validated=True,
        )
        session.add(e)
        await session.flush()
        eid = e.id

    r = await client.post(
        "/api/v1/powderkeg/ticket",
        headers={"X-API-Token": TOKEN},
        json={
            "event_id": eid, "ticker": "005930", "proposed_qty": 10,
            "invalidation_price": 0,   # 무효화 미입력
            "invalidation_logic": "테스트",
            "total_capital_krw": 100_000_000,
            "per_ticker_krw": 3_000_000,
        },
    )
    assert r.status_code == 400
    assert "invalidation_price_required" in r.json()["detail"]
