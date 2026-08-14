"""독약 트윗 방어 회귀 (task #10 · 2026-08-14).

원칙: 파싱 영구 실패 트윗이 매일 크론마다 z.ai 재호출 → 비용 낭비.
N (POISON_PILL_THRESHOLD=3) 회 실패 시 자동 격리 (processed_at 마킹).
"""
from __future__ import annotations

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.discovery.serenity.extractor import (
    POISON_PILL_THRESHOLD,
    _record_failure,
    process_pending_tweets,
)
from backend.services.db import get_session, init_db
from backend.services.models import SerenitySignal, SerenityTweet


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenitySignal))
        await session.execute(delete(SerenityTweet))
        await session.commit()
    yield


async def _seed_tweet(tweet_id: int) -> None:
    async with get_session() as session:
        session.add(SerenityTweet(
            id=str(uuid.uuid4()),
            tweet_id=tweet_id,
            url=f"http://x/{tweet_id}",
            text="poison",
            posted_at=datetime.utcnow() - timedelta(hours=1),
        ))
        await session.commit()


class _FakeToss:
    """항상 예외 발생 (독약 시뮬)."""
    class _Chat:
        def __init__(self, outer):
            self.completions = _FakeToss._Completions(outer)
    class _Completions:
        def __init__(self, outer):
            pass
        def create(self, **kwargs):
            raise RuntimeError("simulated permanent parse failure")
    @property
    def chat(self):
        return _FakeToss._Chat(self)


@pytest.mark.asyncio
async def test_record_failure_increments_and_quarantines():
    """3회 실패 → 자동 격리 (processed_at 마킹)."""
    await _seed_tweet(9999)

    n1 = await _record_failure(9999)
    assert n1 == 1
    n2 = await _record_failure(9999)
    assert n2 == 2
    n3 = await _record_failure(9999)
    assert n3 == POISON_PILL_THRESHOLD

    # 3회 도달 시 processed_at 자동 마킹 (격리)
    from sqlalchemy import select
    async with get_session() as session:
        row = (await session.execute(
            select(SerenityTweet).where(SerenityTweet.tweet_id == 9999)
        )).scalar_one()
    assert row.processed_at is not None, "3회 실패 후 processed_at 자동 마킹 (격리) 실패"
    assert row.extract_failure_count == 3


@pytest.mark.asyncio
async def test_process_pending_records_failure_on_exception():
    """extract 예외 발생 시 failure_count +1 · N회 후 다음 배치 제외."""
    await _seed_tweet(1234)
    client = _FakeToss()

    # 1회: 실패 · failure=1 · processed_at NULL 유지
    r1 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r1["failed"] == 1
    assert r1["tweets"] == 0

    # 2회: 실패 · failure=2
    r2 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r2["failed"] == 1

    # 3회: 실패 · failure=3 → 격리 · processed_at 마킹
    r3 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r3["failed"] == 1

    # 4회: pending 0 (격리 완료) · 추가 z.ai 호출 없음
    r4 = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert r4["pending_before"] == 0, "격리 완료 후 pending 0 (더 이상 처리 시도 X)"
    assert r4["failed"] == 0
