"""18:00 하루 요약 잡 (1022-09 Task 7)."""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.services import notification_digest as nd
from backend.services import notification_log as nl
from backend.services import notification_settings as ns


class _FakeNotifier:
    def __init__(self, fail_categories=()):
        self.calls: list[dict] = []
        self.fail = set(fail_categories)

    async def send(self, level, title, body, force=False, category=None, dedupe_id=None, gate=True):
        self.calls.append({"title": title, "body": body, "force": force, "category": category, "gate": gate})
        return category not in self.fail


@pytest_asyncio.fixture
async def db():
    from backend.services.db import get_session, init_db
    from backend.services.models import NotificationDigestItem, NotificationLog

    await init_db()
    async with get_session() as session:
        await session.execute(delete(NotificationDigestItem))
        await session.execute(delete(NotificationLog))
    yield


async def _queue():
    from backend.services.db import get_session
    from backend.services.models import NotificationDigestItem

    async with get_session() as session:
        return list((await session.execute(select(NotificationDigestItem))).scalars())


@pytest.mark.asyncio
async def test_one_message_per_category_then_clear(db):
    await nl.enqueue_digest("meme_blazing", "밈 A", "b")
    await nl.enqueue_digest("meme_blazing", "밈 B", "b")
    await nl.enqueue_digest("serenity", "Serenity 완료", "b")
    n = _FakeNotifier()
    sent = await nd.send_daily_digest(n)
    assert sent == 2
    by_cat = {c["category"]: c for c in n.calls}
    assert set(by_cat) == {"meme_blazing", "serenity"}
    meme = by_cat["meme_blazing"]
    assert meme["title"] == f"📬 하루 요약 · {ns.CATEGORIES['meme_blazing'].label} 2건"
    assert "밈 A" in meme["body"] and "밈 B" in meme["body"]
    assert f"{ns.SITE_BASE_URL}/lab/meme-watch" in meme["body"]
    assert meme["force"] is True and meme["gate"] is False
    assert await _queue() == []


@pytest.mark.asyncio
async def test_failed_category_stays_in_queue(db):
    await nl.enqueue_digest("meme_blazing", "밈 A", "b")
    await nl.enqueue_digest("serenity", "S", "b")
    sent = await nd.send_daily_digest(_FakeNotifier(fail_categories={"serenity"}))
    assert sent == 1
    assert [i.category for i in await _queue()] == ["serenity"]


@pytest.mark.asyncio
async def test_empty_queue_sends_nothing(db):
    n = _FakeNotifier()
    assert await nd.send_daily_digest(n) == 0
    assert n.calls == []


@pytest.mark.asyncio
async def test_title_list_capped_at_20(db):
    for i in range(25):
        await nl.enqueue_digest("meme_blazing", f"밈 {i}", "b")
    n = _FakeNotifier()
    await nd.send_daily_digest(n)
    body = n.calls[0]["body"]
    assert "밈 19" in body and "밈 20" not in body
    assert "외 5건" in body


@pytest.mark.asyncio
async def test_title_is_html_escaped(db):
    await nl.enqueue_digest("meme_blazing", "A&B <X>", "b")
    n = _FakeNotifier()
    await nd.send_daily_digest(n)
    assert "A&amp;B &lt;X&gt;" in n.calls[0]["body"]


@pytest.mark.asyncio
async def test_cleanup_old_queue_and_logs(db):
    from backend.services.db import get_session
    from backend.services.models import NotificationDigestItem, NotificationLog

    now = nl.utcnow()
    async with get_session() as session:
        session.add(NotificationDigestItem(category="serenity", title="old", body="b", created_at=now - timedelta(days=8)))
        session.add(NotificationLog(category="vip", dedupe_key="k", title="old", result="sent", created_at=now - timedelta(days=31)))
        session.add(NotificationLog(category="vip", dedupe_key="k", title="keep", result="sent", created_at=now - timedelta(days=29)))
    removed = await nd.cleanup()
    assert removed == {"queue": 1, "log": 1}
    async with get_session() as session:
        titles = [r.title for r in (await session.execute(select(NotificationLog))).scalars()]
    assert titles == ["keep"]


def test_cron_registers_daily_digest_at_1800():
    import inspect

    from backend.scheduler import cron

    src = inspect.getsource(cron)
    assert 'CronTrigger(hour=18, minute=0)' in src and 'id="notification_digest_1800"' in src


@pytest.mark.asyncio
async def test_job_wrapper_alerts_on_failure(monkeypatch):
    from backend.scheduler import cron

    async def _boom():
        raise RuntimeError("db locked")

    calls = []

    async def _alert(job_name, exc):
        calls.append(job_name)

    monkeypatch.setattr(nd, "run_daily", _boom)
    monkeypatch.setattr(cron, "_alert_job_failure", _alert)
    await cron.job_notification_digest()
    assert calls == ["알림 하루 요약"]
