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


# ─── 1025-07 · 셋째 자동 주문 경로 (signal_router · EXECUTION_ENABLED) ───
@pytest.mark.asyncio
async def test_status_signal_router_default_off(client, monkeypatch):
    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    r = await client.get("/api/v1/sniper/status")
    assert r.json()["signal_router_enabled"] is False


@pytest.mark.asyncio
async def test_status_signal_router_on(client, monkeypatch):
    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    r = await client.get("/api/v1/sniper/status")
    assert r.json()["signal_router_enabled"] is True


def test_status_uses_signal_router_enabled():
    """같은 값을 따로 해석하지 않는다 (Fable 1025-07 조건)."""
    import inspect

    from backend.api.routes import sniper

    assert "SignalRouter.enabled()" in inspect.getsource(sniper.sniper_status)
