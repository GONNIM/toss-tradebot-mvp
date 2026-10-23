"""TelegramNotifier.send 거름·간격·요약 대기·기록 (1022-09 Task 2).

httpx 를 가짜로 바꾸므로 real_notifier_send 표시로 conftest 의 send 차단을 풉니다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.services import notification_settings as ns
from backend.services import notifier as notifier_mod
from backend.services.notifier import Level, TelegramConfig, TelegramNotifier

pytestmark = pytest.mark.real_notifier_send

TOKEN = "123456:SECRET-TOKEN-abc"


class _FakeResp:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", f"https://api.telegram.org/bot{TOKEN}/sendMessage")
            raise httpx.HTTPStatusError(f"error for url https://api.telegram.org/bot{TOKEN}/sendMessage", request=req, response=httpx.Response(self.status_code, text=self.text, request=req))


class _FakeClient:
    posts: list = []
    status = 200
    exc: Exception | None = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def post(self, url, json=None):
        if _FakeClient.exc is not None:
            raise _FakeClient.exc
        _FakeClient.posts.append(json)
        return _FakeResp(_FakeClient.status, "Bad Request: can't parse entities")


@pytest_asyncio.fixture
async def env(monkeypatch):
    from backend.services.db import get_session, init_db
    from backend.services.models import NotificationDigestItem, NotificationLog, NotificationSetting

    await init_db()
    async with get_session() as session:
        for model in (NotificationSetting, NotificationLog, NotificationDigestItem):
            await session.execute(delete(model))
    ns.invalidate_cache()
    _FakeClient.posts = []
    _FakeClient.status = 200
    _FakeClient.exc = None
    monkeypatch.setattr(notifier_mod.httpx, "AsyncClient", _FakeClient)
    monkeypatch.delenv("TELEGRAM_PROFILE", raising=False)
    yield TelegramNotifier(TelegramConfig(bot_token=TOKEN, chat_id="1"))
    ns.invalidate_cache()


async def _logs():
    from backend.services.db import get_session
    from backend.services.models import NotificationLog

    async with get_session() as session:
        return list((await session.execute(select(NotificationLog).order_by(NotificationLog.id))).scalars())


async def _queue():
    from backend.services.db import get_session
    from backend.services.models import NotificationDigestItem

    async with get_session() as session:
        return list((await session.execute(select(NotificationDigestItem))).scalars())


@pytest.mark.asyncio
async def test_default_sends_and_records(env):
    assert await env.send_info("t1", "b", category="vip") is True
    assert len(_FakeClient.posts) == 1
    logs = await _logs()
    assert [(l.category, l.result) for l in logs] == [("vip", "sent")]


@pytest.mark.asyncio
async def test_disabled_skips_without_http(env):
    await ns.save_setting("serenity", enabled=False)
    assert await env.send_info("Serenity 완료", "b", category="serenity") is False
    assert _FakeClient.posts == []
    assert [l.result for l in await _logs()] == ["skipped"]


@pytest.mark.asyncio
async def test_locked_cannot_be_silenced(env, monkeypatch):
    # 저장 API 는 막지만, 혹시 DB 에 꺼짐 행이 있어도 잠긴 종류는 보낸다
    async def _off(category):
        return ns.SettingView(enabled=False)

    monkeypatch.setattr(ns, "_load_row", _off)
    assert await env.send_critical("Kill Switch 발동", "b", category="kill_switch") is True


@pytest.mark.asyncio
async def test_min_level_filters_info(env):
    await ns.save_setting("serenity", min_level="warning")
    assert await env.send_info("성공", "b", category="serenity") is False
    assert await env.send_warning("실패", "b", category="serenity") is True
    assert len(_FakeClient.posts) == 1


@pytest.mark.asyncio
async def test_resend_interval_by_dedupe_id(env):
    await ns.save_setting("vip", resend_minutes=60)
    assert await env.send_info("VIP 1", "b1", category="vip", dedupe_id="WEN") is True
    assert await env.send_info("VIP 2", "b2", category="vip", dedupe_id="WEN") is False
    assert await env.send_info("VIP 3", "b3", category="vip", dedupe_id="MSFT") is True


@pytest.mark.asyncio
async def test_resend_interval_counts_queued(env):
    await ns.save_setting("meme_blazing", mode="digest", resend_minutes=60)
    await env.send_info("밈 A", "b", category="meme_blazing", dedupe_id="GME")
    await env.send_info("밈 A 다시", "b", category="meme_blazing", dedupe_id="GME")
    assert len(await _queue()) == 1


@pytest.mark.asyncio
async def test_digest_queues_without_http(env):
    await ns.save_setting("meme_blazing", mode="digest")
    assert await env.send_info("밈", "본문", category="meme_blazing") is False
    assert _FakeClient.posts == []
    q = await _queue()
    assert [(i.category, i.title) for i in q] == [("meme_blazing", "밈")]
    assert [l.result for l in await _logs()] == ["queued"]


@pytest.mark.asyncio
async def test_gate_false_bypasses_digest(env):
    await ns.save_setting("meme_blazing", mode="digest")
    assert await env.send(Level.INFO, "요약", "b", force=True, category="meme_blazing", gate=False) is True
    assert await _queue() == []


@pytest.mark.asyncio
async def test_queue_write_failure_sends_immediately(env, monkeypatch):
    from backend.services import notification_log as nl

    await ns.save_setting("meme_blazing", mode="digest")

    async def _boom(*a, **kw):
        raise RuntimeError("locked")

    monkeypatch.setattr(nl, "enqueue_digest", _boom)
    assert await env.send_info("밈", "b", category="meme_blazing") is True


@pytest.mark.asyncio
async def test_log_write_failure_does_not_block(env, monkeypatch):
    from backend.services import notification_log as nl

    async def _boom(*a, **kw):
        raise RuntimeError("locked")

    monkeypatch.setattr(nl, "_insert", _boom)
    assert await env.send_info("t", "b", category="vip") is True


@pytest.mark.asyncio
async def test_no_tables_still_sends(monkeypatch):
    """표가 아직 없는 프로세스(cron·biotech) — 설정 읽기·기록 실패여도 발송."""
    from backend.services import notification_log as nl

    async def _no_table(*a, **kw):
        raise RuntimeError("no such table: notification_setting")

    ns.invalidate_cache()
    monkeypatch.setattr(ns, "_load_row", _no_table)
    monkeypatch.setattr(nl, "_insert", _no_table)
    monkeypatch.setattr(nl, "last_activity_at", _no_table)
    _FakeClient.posts = []
    _FakeClient.exc = None
    _FakeClient.status = 200
    monkeypatch.setattr(notifier_mod.httpx, "AsyncClient", _FakeClient)
    n = TelegramNotifier(TelegramConfig(bot_token=TOKEN, chat_id="1"))
    assert await n.send_info("t", "b", category="vip") is True
    ns.invalidate_cache()


@pytest.mark.asyncio
async def test_unknown_category_sends_and_records(env):
    assert await env.send_info("새 알림", "b") is True
    assert [(l.category, l.result) for l in await _logs()] == [("unknown", "sent")]


@pytest.mark.asyncio
async def test_force_does_not_bypass_settings(env):
    """send_critical(force) 도 끈 종류면 건너뜀 — force 는 프로필·중복 억제 우회만."""
    await ns.save_setting("powderkeg_dnt", enabled=False)
    assert await env.send_critical("화약고 거래 주의", "b", category="powderkeg_dnt") is False


@pytest.mark.asyncio
async def test_http_error_record_has_no_token(env):
    _FakeClient.status = 400
    assert await env.send_info("t", "b", category="vip") is False
    log = (await _logs())[-1]
    assert log.result == "failed"
    assert "HTTP 400" in log.error
    assert TOKEN not in log.error


@pytest.mark.asyncio
async def test_other_error_record_has_no_token(env):
    _FakeClient.exc = RuntimeError(f"connect fail https://api.telegram.org/bot{TOKEN}/sendMessage")
    assert await env.send_info("t", "b", category="vip") is False
    log = (await _logs())[-1]
    assert log.result == "failed"
    assert TOKEN not in log.error
    assert "RuntimeError" in log.error


@pytest.mark.asyncio
async def test_profile_source_from_category(env, monkeypatch):
    """제목이 한글이어도 category 로 프로필 출처를 정함 (SNIPER 는 kill_switch 통과)."""
    monkeypatch.setenv("TELEGRAM_PROFILE", "SNIPER")
    assert await env.send_info("시스템이 멈췄습니다", "b", category="kill_switch") is True
    assert await env.send_info("섹터 리더 3종목", "b", category="discovery_sector") is False
