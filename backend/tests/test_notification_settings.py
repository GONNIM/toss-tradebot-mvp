"""알림 설정 표·캐시 (1022-09 Task 1)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.services import notification_settings as ns


@pytest_asyncio.fixture
async def clean_db():
    from backend.services.db import get_session, init_db
    from backend.services.models import NotificationDigestItem, NotificationLog, NotificationSetting

    await init_db()
    async with get_session() as session:
        for model in (NotificationSetting, NotificationLog, NotificationDigestItem):
            await session.execute(delete(model))
    ns.invalidate_cache()
    yield
    ns.invalidate_cache()


def test_categories_locked_and_meta():
    assert ns.LOCKED == {"kill_switch", "execution", "system"}
    for key, meta in ns.CATEGORIES.items():
        assert meta.label and meta.group and meta.page.startswith("/"), key
        assert meta.locked == (key in ns.LOCKED)
    assert ns.SITE_BASE_URL == "https://optimus8.cafe24.com"
    # 권고값 예시 (README 2026-10-22 유용성 권고)
    assert ns.CATEGORIES["serenity"].recommended == {"min_level": "warning"}
    assert ns.CATEGORIES["powderkeg_a2"].recommended == {"enabled": False}
    assert ns.CATEGORIES["meme_blazing"].recommended == {"mode": "digest"}
    assert ns.CATEGORIES["vip"].recommended == {"resend_minutes": 10080}


@pytest.mark.asyncio
async def test_missing_row_returns_default(clean_db):
    view = await ns.get_setting("serenity")
    assert view == ns.SettingView(enabled=True, mode="immediate", resend_minutes=0, min_level="info")


@pytest.mark.asyncio
async def test_db_error_returns_default(monkeypatch):
    ns.invalidate_cache()

    class _Boom:
        def __call__(self, *a, **kw):
            raise RuntimeError("no table")

    monkeypatch.setattr(ns, "_load_row", _Boom())
    view = await ns.get_setting("vip")
    assert view.enabled is True and view.mode == "immediate"
    ns.invalidate_cache()


@pytest.mark.asyncio
async def test_saved_row_and_cache(clean_db, monkeypatch):
    await ns.save_setting("vip", enabled=False, resend_minutes=60)
    view = await ns.get_setting("vip")
    assert view.enabled is False and view.resend_minutes == 60

    calls = []
    real = ns._load_row

    async def _counting(category):
        calls.append(category)
        return await real(category)

    monkeypatch.setattr(ns, "_load_row", _counting)
    ns.invalidate_cache()
    await ns.get_setting("vip")
    await ns.get_setting("vip")
    assert calls == ["vip"]  # 60초 캐시 안에서는 다시 읽지 않음


@pytest.mark.asyncio
async def test_save_rejects_disabling_locked(clean_db):
    with pytest.raises(ValueError):
        await ns.save_setting("kill_switch", enabled=False)
    # 잠긴 종류도 모드는 바꿀 수 있음 (system 은 하루 요약 허용)
    await ns.save_setting("system", mode="digest")
    assert (await ns.get_setting("system")).mode == "digest"


def test_engine_has_sqlite_busy_timeout():
    from backend.services import db

    if db.DATABASE_URL.startswith("sqlite"):
        assert db._connect_args() == {"timeout": 5}
    assert db._connect_args_for("postgresql+asyncpg://x") == {}


def test_every_category_page_exists_in_frontend():
    """자세히 보기 링크가 실제 화면으로 이어짐 (frontend/app/<page>/page.tsx)."""
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "frontend" / "app"
    for key, meta in {**ns.CATEGORIES, **ns.DISPLAY_ONLY}.items():
        if meta.page == "/admin/notifications":
            continue  # Task 6 에서 만듦
        assert (app / meta.page.strip("/") / "page.tsx").exists(), (key, meta.page)
