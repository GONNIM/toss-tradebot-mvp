"""1119-04 · 알림 기록이 쓰기 잠금에 막혀 빠지던 문제 (notification_log 짧은 시도 + 대기열).

메모리 DB 는 연결 하나를 모두가 나눠 써서 잠금을 만들 수 없다 → 임시 파일 SQLite 엔진으로 바꿔 쓴다.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.services import notification_log as nl
from backend.services import notification_settings as ns
from backend.services import notifier as notifier_mod
from backend.services.notifier import TelegramConfig, TelegramNotifier

pytestmark = pytest.mark.real_notifier_send


class _Resp:
    status_code = 200
    text = "ok"

    def raise_for_status(self):
        pass


class _Client:
    posts: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def post(self, url, json=None):
        _Client.posts.append(json)
        return _Resp()


@pytest_asyncio.fixture
async def file_db(monkeypatch, tmp_path):
    from backend.services import db
    from backend.services.models import Base

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}", connect_args={"timeout": 30})

    @event.listens_for(eng.sync_engine, "connect")
    def _busy(conn, _r):
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    import backend.execution.plan.models  # noqa: F401  (표 등록)
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "AsyncSessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    monkeypatch.setattr(nl, "FAST_WRITE_SECONDS", 0.3)
    monkeypatch.setattr(notifier_mod.httpx, "AsyncClient", _Client)
    _Client.posts = []
    nl.reset_pending()
    ns.invalidate_cache()
    yield eng
    nl.reset_pending()
    ns.invalidate_cache()
    await eng.dispose()


def _notifier():
    return TelegramNotifier(TelegramConfig(bot_token="123456:TEST-TOKEN", chat_id="1"))


async def _logs():
    from backend.services.db import get_session
    from backend.services.models import NotificationLog

    async with get_session() as s:
        return list((await s.execute(select(NotificationLog).order_by(NotificationLog.id))).scalars())


async def _hold_lock(eng):
    """다른 연결이 쓰기 잠금을 쥔다 (BEGIN IMMEDIATE)."""
    conn = await eng.connect()
    await conn.exec_driver_sql("BEGIN IMMEDIATE")
    return conn


@pytest.mark.asyncio
async def test_a_send_under_write_lock_returns_fast_then_flush_writes_one_sent(file_db):
    holder = await _hold_lock(file_db)
    t0 = time.monotonic()
    assert await _notifier().send_info("잠금 중 알림", "b", category="vip") is True
    assert time.monotonic() - t0 < 2.0                      # 30초 기다리지 않는다
    assert nl.pending_count() == 1
    await holder.rollback()
    await holder.close()
    assert await nl.flush_pending() == 0
    rows = await _logs()
    assert [(r.category, r.result) for r in rows] == [("vip", "sent")]


def test_b_asyncio_run_once_still_records_sent(file_db):
    """막음 A · 한 번 돌고 끝나는 경로(asyncio.run)에서 잠금이 없으면 기록이 바로 남는다."""
    import asyncio

    asyncio.run(_notifier().send_info("한 번 실행", "b", category="vip"))
    loop2 = asyncio.new_event_loop()
    try:
        rows = loop2.run_until_complete(_logs())
    finally:
        loop2.close()
    assert [(r.category, r.result) for r in rows] == [("vip", "sent")]


@pytest.mark.asyncio
async def test_d_pending_sent_blocks_resend_within_interval(file_db):
    await ns.save_setting("vip", resend_minutes=30)
    holder = await _hold_lock(file_db)
    assert await _notifier().send_info("같은 알림", "b1", category="vip") is True
    # 기록이 메모리 대기열에만 있어도 재발송 간격이 막는다 (다른 알림 객체 = 메모리 60초 억제와 무관)
    assert nl.pending_count() == 1
    assert await _notifier().send_info("같은 알림", "b2 다른 본문", category="vip") is False
    assert len(_Client.posts) == 1
    await holder.rollback()
    await holder.close()
    await nl.flush_pending()
    # 기록이 DB 에 쓰인 뒤에도 막는다
    assert await _notifier().send_info("같은 알림", "b3", category="vip") is False
    assert len(_Client.posts) == 1
    assert [r.result for r in await _logs()].count("sent") == 1


@pytest.mark.asyncio
async def test_queue_limit_drops_with_warning(file_db, monkeypatch, caplog):
    monkeypatch.setattr(nl, "QUEUE_LIMIT", 2)
    holder = await _hold_lock(file_db)
    for i in range(3):
        await nl.record("vip", f"k{i}", "t", "sent")
    assert nl.pending_count() == 2
    assert any("대기열 가득" in r.message for r in caplog.records)
    await holder.rollback()
    await holder.close()


@pytest.mark.asyncio
async def test_c_job_plan_draft_notifies_after_commit(file_db, monkeypatch, tmp_path):
    from sqlalchemy import select as sel

    from backend.execution.plan import drafts, runner
    from backend.execution.plan.models import PlanEvent
    from backend.services.db import get_session

    seen = []

    async def fake_notify(level, title, body, category):
        async with get_session() as s:     # 새 세션 = 커밋된 것만 보인다
            n = await s.scalar(sel(PlanEvent.id).where(PlanEvent.kind == "draft_done").limit(1))
        seen.append((title, n is not None))

    monkeypatch.setattr(runner, "default_notify", fake_notify)
    monkeypatch.setenv("PLAN_RADAR_DIR", str(tmp_path))
    kst = drafts._KST

    def utc(day, h, m):
        return datetime(2026, 11, day, h, m, tzinfo=kst).astimezone(timezone.utc).replace(tzinfo=None)

    # 「자동 초안 없음」 경로
    assert await runner.job_plan_draft(utc(20, 8, 5)) == "warned"
    # 요약 알림 경로 (run_draft_cycle 만 초안 1건 · 요약 있음으로 대체)
    (tmp_path / "radar_v1_3_20261121.csv").write_text("ticker,name\nTESTA,a\n", encoding="utf-8")

    class _D:
        action = "create"

    async def fake_cycle(s, eng, **kw):
        return [_D()], []

    monkeypatch.setattr(drafts, "run_draft_cycle", fake_cycle)
    monkeypatch.setattr(drafts, "build_summary", lambda d, e, names: ("자동 초안 1건", "본문"))
    assert await runner.job_plan_draft(utc(21, 7, 15)) == "drafted"
    assert seen == [("자동 초안 없음", True), ("자동 초안 1건", True)]


# ── 막음 H · 짧은 busy_timeout 이 풀에 남지 않는다 ─────────────────

async def _warm_pool(eng, n=3):
    """쉬는 연결을 n개 만든다 (동시에 꺼냈다 돌려줌)."""
    conns = [await eng.connect() for _ in range(n)]
    for c in conns:
        await c.exec_driver_sql("SELECT 1")
    for c in conns:
        await c.close()


async def _pool_busy_values(eng, n=3):
    conns = [await eng.connect() for _ in range(n)]
    try:
        vals = []
        for c in conns:
            vals.append((await c.exec_driver_sql("PRAGMA busy_timeout")).scalar())
        return vals
    finally:
        for c in conns:
            await c.close()


@pytest.mark.asyncio
async def test_h1_pool_busy_timeout_restored_after_success(file_db):
    await _warm_pool(file_db)
    await nl.record("vip", "k", "t", "sent")
    assert nl.pending_count() == 0
    assert await _pool_busy_values(file_db) == [30000, 30000, 30000]


@pytest.mark.asyncio
async def test_h2_pool_busy_timeout_restored_after_lock_failure(file_db):
    await _warm_pool(file_db)
    holder = await _hold_lock(file_db)
    await nl.record("vip", "k", "t", "sent")
    assert nl.pending_count() == 1
    await holder.rollback()
    await holder.close()
    assert await _pool_busy_values(file_db) == [30000, 30000, 30000]


@pytest.mark.asyncio
async def test_h3_plain_write_after_record_waits_for_lock(file_db):
    import asyncio

    from backend.services.db import get_session
    from backend.services.models import NotificationLog

    await _warm_pool(file_db)
    await nl.record("vip", "k", "t", "sent")
    holder = await _hold_lock(file_db)

    async def _release():
        await asyncio.sleep(2.5)
        await holder.rollback()
        await holder.close()

    rel = asyncio.create_task(_release())
    t0 = time.monotonic()
    async with get_session() as s:     # 평범한 쓰기 · 1.5초에 포기하면 안 된다
        s.add(NotificationLog(category="vip", dedupe_key="x", title="y", result="sent", created_at=nl.utcnow()))
    assert time.monotonic() - t0 >= 2.0
    await rel
