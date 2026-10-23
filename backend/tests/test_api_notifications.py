"""알림 설정 API (1022-09 Task 3)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.services import notification_log as nl
from backend.services import notification_settings as ns

TOKEN = "test-sniper-token-notify"
H = {"X-API-Token": TOKEN}


@pytest_asyncio.fixture
async def client(monkeypatch):
    from backend.services.db import get_session, init_db
    from backend.services.models import NotificationDigestItem, NotificationLog, NotificationSetting, SniperApiAccess

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as session:
        for model in (NotificationSetting, NotificationLog, NotificationDigestItem, SniperApiAccess):
            await session.execute(delete(model))
    ns.invalidate_cache()
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    ns.invalidate_cache()


@pytest.mark.asyncio
async def test_requires_auth(client):
    assert (await client.get("/api/v1/notifications/settings")).status_code == 401


@pytest.mark.asyncio
async def test_list_has_all_categories_and_status(client):
    await nl.record("vip", "WEN", "VIP 1", "sent")
    await nl.record("vip", "WEN", "VIP 2", "failed", "HTTP 400")
    await nl.record("vip", "WEN", "VIP 3", "skipped", "설정: 꺼짐")
    r = await client.get("/api/v1/notifications/settings", headers=H)
    assert r.status_code == 200
    rows = {row["category"]: row for row in r.json()}
    assert set(ns.CATEGORIES) | set(ns.DISPLAY_ONLY) == set(rows)
    vip = rows["vip"]
    assert vip["enabled"] is True and vip["mode"] == "immediate"
    assert vip["label"] == "VIP 감시" and vip["page"] == "/vip"
    assert vip["recommended"] == {"resend_minutes": 10080}
    assert vip["last_sent_at"] and vip["last_failed_at"]
    assert vip["last_error"] == "HTTP 400"
    assert vip["skipped_today"] == 1
    assert rows["kill_switch"]["locked"] is True
    assert rows["deploy"]["configurable"] is False


@pytest.mark.asyncio
async def test_update_partial(client):
    r = await client.put("/api/v1/notifications/settings/serenity", headers=H, json={"min_level": "warning"})
    assert r.status_code == 200
    assert r.json()["min_level"] == "warning" and r.json()["enabled"] is True
    assert (await ns.get_setting("serenity")).min_level == "warning"


@pytest.mark.asyncio
async def test_locked_cannot_be_disabled(client):
    r = await client.put("/api/v1/notifications/settings/kill_switch", headers=H, json={"enabled": False})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_system_digest_allowed(client):
    r = await client.put("/api/v1/notifications/settings/system", headers=H, json={"mode": "digest"})
    assert r.status_code == 200 and r.json()["mode"] == "digest"


@pytest.mark.asyncio
async def test_unknown_category_404(client):
    r = await client.put("/api/v1/notifications/settings/nope", headers=H, json={"enabled": False})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_bad_value_422(client):
    r = await client.put("/api/v1/notifications/settings/vip", headers=H, json={"mode": "weekly"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_apply_recommended(client):
    r = await client.post("/api/v1/notifications/settings/apply-recommended", headers=H)
    assert r.status_code == 200 and r.json()["applied"] > 0
    assert (await ns.get_setting("serenity")).min_level == "warning"
    assert (await ns.get_setting("powderkeg_a2")).enabled is False
    assert (await ns.get_setting("meme_blazing")).mode == "digest"


@pytest.mark.asyncio
async def test_log_by_category(client):
    for i in range(3):
        await nl.record("vip", "WEN", f"VIP {i}", "sent")
    await nl.record("biotech", "x", "바이오", "sent")
    r = await client.get("/api/v1/notifications/log?category=vip&limit=2", headers=H)
    assert r.status_code == 200
    items = r.json()
    assert [i["title"] for i in items] == ["VIP 2", "VIP 1"]
    assert all(i["category"] == "vip" for i in items)
