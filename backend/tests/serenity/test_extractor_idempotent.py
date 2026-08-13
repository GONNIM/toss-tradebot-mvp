"""extractor idempotent · 2026-08-13 무한 루프 사고 회귀 방지.

축 1 (사고 재발 방지 체계) 4 테스트:
  1. signals=[] 반환 트윗은 processed_at 마킹 · 재실행 시 재선택 X
  2. load_pending_tweets 크기 반복 실행 시 반드시 감소
  3. z.ai 예외 시 processed_at NULL 유지 (재시도 대상)
  4. process_pending_tweets pending_before/after 반환값 정합

⚠ 실 파일 DB 오염 방지 · 반드시 in-memory sqlite
"""
from __future__ import annotations

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.discovery.serenity import extractor as ex
from backend.discovery.serenity.extractor import (
    count_pending_tweets,
    load_pending_tweets,
    process_pending_tweets,
)
from backend.services.db import get_session, init_db
from backend.services.models import SerenitySignal, SerenityTweet


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenitySignal))
        await session.execute(delete(SerenityTweet))
        await session.commit()
    yield


async def _seed_tweets(n: int) -> list[int]:
    """n 트윗 · processed_at=NULL · 시퀀셜 tweet_id."""
    now = datetime.utcnow()
    ids: list[int] = []
    async with get_session() as session:
        for i in range(n):
            tid = 1_000_000 + i
            ids.append(tid)
            session.add(SerenityTweet(
                id=str(uuid.uuid4()),
                tweet_id=tid,
                url=f"http://x/{tid}",
                text=f"dummy tweet {i}",
                posted_at=now - timedelta(hours=i),
            ))
        await session.commit()
    return ids


class _FakeClient:
    """z.ai 클라이언트 stub. mode 로 응답 제어."""
    def __init__(self, mode: str = "empty"):
        self.mode = mode
        self.call_count = 0

    class _Chat:
        def __init__(self, outer):
            self._outer = outer
            self.completions = _FakeClient._Completions(outer)

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.call_count += 1
            if self._outer.mode == "raise":
                raise RuntimeError("simulated z.ai failure")
            if self._outer.mode == "empty":
                content = '{"signals": []}'
            else:  # "one_signal"
                content = '{"signals": [{"ticker":"NBIS","sentiment":"bullish","thesis_type":"reaffirmation","evidence_type":"contract","confidence":0.85,"reasoning":"stub"}]}'
            return type("Resp", (), {
                "choices": [type("C", (), {
                    "message": type("M", (), {"content": content})()
                })()],
            })()

    @property
    def chat(self):
        return _FakeClient._Chat(self)


@pytest.mark.asyncio
async def test_empty_signals_marks_processed():
    """z.ai signals=[] 반환 트윗 → processed_at 마킹 → 재실행 시 재선택 X."""
    await _seed_tweets(3)
    client = _FakeClient(mode="empty")

    r1 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r1["tweets"] == 3
    assert r1["signals_inserted"] == 0
    assert r1["failed"] == 0
    assert r1["pending_after"] == 0
    assert client.call_count == 3

    # 재실행 · pending 0 · API 호출 없음
    r2 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r2["tweets"] == 0
    assert client.call_count == 3, "재실행 시 z.ai 재호출 없어야 함 (idempotent)"


@pytest.mark.asyncio
async def test_load_pending_shrinks_after_process():
    """process_pending_tweets 실행 후 load_pending_tweets 크기 반드시 감소."""
    await _seed_tweets(5)
    client = _FakeClient(mode="empty")

    before = len(await load_pending_tweets(limit=100))
    assert before == 5

    await process_pending_tweets(batch_size=3, concurrency=1, client=client)
    after = len(await load_pending_tweets(limit=100))
    assert after == 2, f"pending 감소 실패 · before={before} after={after}"


@pytest.mark.asyncio
async def test_extractor_failure_does_not_mark():
    """z.ai 예외 시 processed_at NULL 유지 · 재실행 시 재시도 대상."""
    await _seed_tweets(2)
    client = _FakeClient(mode="raise")

    r = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r["tweets"] == 0, "실패 트윗은 마킹 X · tweets 카운트 미포함"
    assert r["failed"] == 2
    assert r["pending_after"] == 2, "실패 시 pending 감소 없어야 함"

    # 재시도 시 다시 시도됨
    r2 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r2["failed"] == 2, "실패 트윗 재시도 확인"


@pytest.mark.asyncio
async def test_pending_before_after_reported():
    """반환값에 pending_before/after 포함 · 정합."""
    await _seed_tweets(4)
    client = _FakeClient(mode="one_signal")

    r = await process_pending_tweets(batch_size=2, concurrency=1, client=client)
    assert r["pending_before"] == 4
    assert r["pending_after"] == 2
    assert r["tweets"] == 2
    assert r["signals_inserted"] == 2  # 트윗당 signal 1건 · 2 트윗


@pytest.mark.asyncio
async def test_infinite_loop_detection():
    """마킹 결함이 있으면 RuntimeError raise (회귀 방지 게이트)."""
    await _seed_tweets(2)
    client = _FakeClient(mode="empty")

    # _mark_processed 를 monkeypatch 로 무력화 → 사고 재현
    original = ex._mark_processed

    async def _noop(_tid: int) -> None:
        pass

    ex._mark_processed = _noop
    try:
        with pytest.raises(RuntimeError, match="무한 루프 감지"):
            await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    finally:
        ex._mark_processed = original


@pytest.mark.asyncio
async def test_count_pending_matches_load_pending():
    """count_pending_tweets · load_pending_tweets 카운트 정합."""
    await _seed_tweets(7)
    assert await count_pending_tweets() == 7
    assert len(await load_pending_tweets(limit=100)) == 7
