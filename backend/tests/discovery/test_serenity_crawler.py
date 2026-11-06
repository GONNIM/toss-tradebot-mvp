"""Serenity Crawler 단위 테스트 · Phase L2 · 2026-08-02."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.serenity.crawler import (
    _to_row,
    load_archive_tweets,
    sync_tweets,
)
from backend.services.db import get_session, init_db
from backend.services.models import SerenityTweet


FIXTURE_TWEETS = [
    {
        "id": "2083438823548293140",
        "text": "$LITE CEO warned laser supply gap.",
        "author": {"screenName": "aleabitoreddit"},
        "metrics": {"likes": 1481, "retweets": 115, "replies": 109, "views": 219060},
        "createdAt": "Sat Aug 01 06:24:58 +0000 2026",
        "createdAtISO": "2026-08-01T06:24:58+00:00",
        "isReply": False,
        "isQuote": False,
    },
    {
        "id": "2083329679822671917",
        "text": "@optionsreaper reply text",
        "metrics": {"likes": 40},
        "createdAtISO": "2026-07-31T23:11:16+00:00",
        "isReply": True,
        "inReplyToTweetId": "2083326216950645015",
    },
    {
        "id": "2083300000000000001",
        "text": "quote example",
        "metrics": {"likes": 5},
        "createdAtISO": "2026-07-30T12:00:00+00:00",
        "isQuote": True,
        "quotedStatusId": "2083200000000000000",
    },
]


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenityTweet))
    yield


@pytest.fixture
def tracker_dir(tmp_path: Path) -> Path:
    """임시 tracker_dir + data/aleabitoreddit_tweets.json fixture."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "aleabitoreddit_tweets.json").write_text(
        json.dumps(FIXTURE_TWEETS), encoding="utf-8",
    )
    return tmp_path


# ─── _to_row (파싱 단위 테스트) ────────────────────────────────────


def test_to_row_basic():
    row = _to_row(FIXTURE_TWEETS[0])
    assert row is not None
    assert row.tweet_id == 2083438823548293140
    assert row.url == "https://x.com/aleabitoreddit/status/2083438823548293140"
    assert row.text.startswith("$LITE")
    assert row.reply_to_id is None
    assert row.quoted_id is None
    m = json.loads(row.metrics)
    assert m["likes"] == 1481
    assert row.posted_at.year == 2026


def test_to_row_reply():
    row = _to_row(FIXTURE_TWEETS[1])
    assert row.reply_to_id == 2083326216950645015


def test_to_row_quote():
    row = _to_row(FIXTURE_TWEETS[2])
    assert row.quoted_id == 2083200000000000000


def test_to_row_invalid_id():
    assert _to_row({"id": "not-a-number", "createdAtISO": "2026-01-01T00:00:00+00:00"}) is None


def test_to_row_invalid_iso():
    assert _to_row({"id": "1", "createdAtISO": None}) is None


# ─── load_archive_tweets ─────────────────────────────────────────


def test_load_archive_tweets_returns_list(tracker_dir: Path):
    tweets = load_archive_tweets(tracker_dir)
    assert isinstance(tweets, list) and len(tweets) == 3


def test_load_archive_tweets_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_archive_tweets(tmp_path)


# ─── sync_tweets · 증분 로직 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_tweets_first_run_inserts_all(tracker_dir: Path):
    result = await sync_tweets(tracker_dir=tracker_dir)
    assert result["inserted"] == 3
    assert result["skipped"] == 0
    assert result["invalid"] == 0
    assert result["total_archive"] == 3

    async with get_session() as session:
        total = (await session.execute(select(func.count(SerenityTweet.id)))).scalar_one()
    assert total == 3


@pytest.mark.asyncio
async def test_sync_tweets_second_run_all_skipped(tracker_dir: Path):
    await sync_tweets(tracker_dir=tracker_dir)
    result = await sync_tweets(tracker_dir=tracker_dir)
    assert result["inserted"] == 0
    assert result["skipped"] == 3   # 모두 dedup


@pytest.mark.asyncio
async def test_sync_tweets_incremental_new_only(tracker_dir: Path):
    """첫 sync 이후 fixture 에 1건 추가하면 그것만 insert."""
    await sync_tweets(tracker_dir=tracker_dir)

    extra = dict(FIXTURE_TWEETS[0])
    extra["id"] = "9999999999999999"
    extra["createdAtISO"] = "2026-08-02T00:00:00+00:00"
    combined = FIXTURE_TWEETS + [extra]
    (tracker_dir / "data" / "aleabitoreddit_tweets.json").write_text(
        json.dumps(combined), encoding="utf-8",
    )

    result = await sync_tweets(tracker_dir=tracker_dir)
    assert result["inserted"] == 1
    assert result["skipped"] == 3

    async with get_session() as session:
        total = (await session.execute(select(func.count(SerenityTweet.id)))).scalar_one()
    assert total == 4


@pytest.mark.asyncio
async def test_sync_tweets_invalid_id_counted(tracker_dir: Path):
    bad = [{"id": "abc", "createdAtISO": "2026-01-01T00:00:00+00:00", "text": "x"}]
    (tracker_dir / "data" / "aleabitoreddit_tweets.json").write_text(
        json.dumps(bad), encoding="utf-8",
    )
    result = await sync_tweets(tracker_dir=tracker_dir)
    assert result["inserted"] == 0
    assert result["invalid"] == 1


# ─── 1106-02 · 동기 호출이 이벤트 루프를 막지 않음 (교훈 #3) ─────────────


@pytest.mark.asyncio
async def test_sync_tweets_does_not_block_event_loop(tracker_dir: Path, monkeypatch):
    """git pull·아카이브 읽기가 1초씩 걸려도 같은 루프의 다른 일이 계속 돈다.

    예전처럼 동기로 부르면 2초 동안 루프가 멈춰 tick 이 거의 0 이 된다.
    """
    import asyncio
    import time

    import backend.discovery.serenity.crawler as crawler

    real_load = crawler.load_archive_tweets

    def slow_pull(_dir):
        time.sleep(1.0)
        return "abc1234"

    def slow_load(d):
        time.sleep(1.0)
        return real_load(d)

    monkeypatch.setattr(crawler, "_auto_pull_submodule", slow_pull)
    monkeypatch.setattr(crawler, "load_archive_tweets", slow_load)

    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.05)
            ticks += 1

    t = asyncio.create_task(ticker())
    result = await crawler.sync_tweets(tracker_dir=tracker_dir, auto_pull=True)
    stop.set()
    await t

    assert result["submodule_sha"] == "abc1234"
    assert result["inserted"] == 3
    # 2초 동안 0.05초 간격 → 막히지 않으면 약 40회. 느린 기계 여유로 20 이상.
    assert ticks >= 20, f"이벤트 루프가 막힘 · ticks={ticks}"
