"""1025-01 · /sniper 안전 상황판 서버 쪽 (주문 대상 · Kill Switch 화면 링크)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from backend.api.main import app
    from backend.services.db import init_db

    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_status_order_target_default_paper(client, monkeypatch):
    monkeypatch.delenv("EXECUTION_BROKER", raising=False)
    r = await client.get("/api/v1/sniper/status")
    assert r.status_code == 200
    assert r.json()["order_target"] == "paper"


@pytest.mark.asyncio
async def test_status_order_target_toss(client, monkeypatch):
    monkeypatch.setenv("EXECUTION_BROKER", "TOSS")
    r = await client.get("/api/v1/sniper/status")
    assert r.json()["order_target"] == "toss"


@pytest.mark.asyncio
async def test_status_order_target_unknown_is_paper(client, monkeypatch):
    monkeypatch.setenv("EXECUTION_BROKER", "kiwoom")
    r = await client.get("/api/v1/sniper/status")
    assert r.json()["order_target"] == "paper"


def test_kill_switch_setting_page_is_sniper():
    from backend.services import notification_settings as ns

    assert ns.CATEGORIES["kill_switch"].page == "/sniper"
