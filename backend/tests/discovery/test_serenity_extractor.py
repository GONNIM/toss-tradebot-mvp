"""Serenity Extractor mock 기반 단위 테스트 · Phase L3 · 2026-08-02.

실 z.ai 호출 없이 파싱·race·pending 조회·정규화만 검증.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.serenity.extractor import (
    _sanitize_signal,
    extract_signals,
    load_pending_tweets,
    load_system_prompt,
    process_pending_tweets,
)
from backend.services.db import get_session, init_db
from backend.services.models import SerenitySignal, SerenityTweet


# ─── fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenitySignal))
        await session.execute(delete(SerenityTweet))
    yield


def _make_tweet(tid: int, text: str) -> SerenityTweet:
    return SerenityTweet(
        id=str(uuid.uuid4()),
        tweet_id=tid,
        url=f"https://x.com/aleabitoreddit/status/{tid}",
        posted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        text=text,
        metrics=json.dumps({"likes": 10}),
        raw_json=json.dumps({"id": str(tid), "text": text}),
    )


def _fake_client(response_json: dict) -> MagicMock:
    """openai 호환 mock client · chat.completions.create 응답 고정."""
    fake = MagicMock()
    fake.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(response_json),
        ))]
    )
    return fake


# ─── system.md 로드 ──────────────────────────────────────────────


def test_load_system_prompt_returns_text():
    text = load_system_prompt()
    assert "Serenity" in text and "15원칙" in text
    assert len(text) > 500


# ─── _sanitize_signal ────────────────────────────────────────────


def test_sanitize_signal_valid():
    out = _sanitize_signal({
        "ticker": "$nbis",
        "sentiment": "bullish",
        "thesis_type": "new_bottleneck",
        "evidence_type": "earnings",
        "confidence": 0.85,
        "reasoning": " test  ",
    })
    assert out["ticker"] == "NBIS"          # 대문자 + $ 제거
    assert out["sentiment"] == "bullish"
    assert out["thesis_type"] == "new_bottleneck"
    assert out["evidence_type"] == "earnings"
    assert out["confidence"] == 0.85
    assert out["reasoning"] == "test"


def test_sanitize_signal_invalid_sentiment_returns_none():
    assert _sanitize_signal({"ticker": "NBIS", "sentiment": "wrong"}) is None


def test_sanitize_signal_missing_ticker_returns_none():
    assert _sanitize_signal({"sentiment": "bullish"}) is None


def test_sanitize_signal_unknown_thesis_type_dropped():
    out = _sanitize_signal({
        "ticker": "NBIS", "sentiment": "bullish", "thesis_type": "unknown_x",
    })
    assert out["thesis_type"] is None


def test_sanitize_signal_confidence_clamped():
    out = _sanitize_signal({"ticker": "A", "sentiment": "bullish", "confidence": 1.5})
    assert out["confidence"] == 1.0
    out2 = _sanitize_signal({"ticker": "A", "sentiment": "bullish", "confidence": -0.5})
    assert out2["confidence"] == 0.0


# ─── extract_signals (mock openai) ────────────────────────────────


def test_extract_signals_returns_list():
    client = _fake_client({
        "signals": [
            {"ticker": "NBIS", "sentiment": "bullish", "confidence": 0.9},
            {"ticker": "$AXTI", "sentiment": "neutral", "thesis_type": "watchlist"},
        ]
    })
    out = extract_signals("test tweet", None, client=client)
    assert len(out) == 2
    assert out[0]["ticker"] == "NBIS"
    assert out[1]["ticker"] == "AXTI"


def test_extract_signals_empty_when_no_signals():
    client = _fake_client({"signals": []})
    assert extract_signals("noise", None, client=client) == []


def test_extract_signals_handles_invalid_json():
    fake = MagicMock()
    fake.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not-a-json"))]
    )
    assert extract_signals("x", None, client=fake) == []


def test_extract_signals_filters_bad_entries():
    client = _fake_client({
        "signals": [
            {"ticker": "NBIS", "sentiment": "bullish"},
            {"ticker": "", "sentiment": "bullish"},               # 불량 · 제외
            {"sentiment": "wrong"},                                # 불량 · 제외
            "not-a-dict",                                          # 불량 · 제외
        ]
    })
    out = extract_signals("x", None, client=client)
    assert len(out) == 1 and out[0]["ticker"] == "NBIS"


# ─── load_pending_tweets ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_pending_tweets_excludes_processed():
    async with get_session() as session:
        session.add_all([
            _make_tweet(1, "processed"),
            _make_tweet(2, "pending"),
        ])
        session.add(SerenitySignal(
            id=str(uuid.uuid4()),
            tweet_id=1, ticker="X", sentiment="bullish", confidence=0.5,
        ))
        await session.commit()

    pending = await load_pending_tweets(limit=10)
    assert [t.tweet_id for t in pending] == [2]


# ─── process_pending_tweets (mock) ────────────────────────────────


@pytest.mark.asyncio
async def test_process_pending_tweets_inserts_signals():
    async with get_session() as session:
        session.add(_make_tweet(100, "$NBIS 언급"))
        await session.commit()

    client = _fake_client({
        "signals": [
            {"ticker": "NBIS", "sentiment": "bullish", "confidence": 0.9},
        ]
    })
    result = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert result == {"tweets": 1, "signals_inserted": 1, "failed": 0}

    async with get_session() as session:
        n = (await session.execute(select(func.count(SerenitySignal.id)))).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_process_pending_tweets_no_pending_returns_zero():
    client = _fake_client({"signals": []})
    result = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert result == {"tweets": 0, "signals_inserted": 0, "failed": 0}


@pytest.mark.asyncio
async def test_process_pending_tweets_extract_failure_counted():
    """openai 호출 예외 시 failed +1 · 다른 트윗 계속 진행."""
    async with get_session() as session:
        session.add_all([_make_tweet(200, "a"), _make_tweet(201, "b")])
        await session.commit()

    client = MagicMock()
    calls = {"n": 0}

    def _side_effect(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("z.ai 500")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"signals": [{"ticker": "OK", "sentiment": "bullish"}]}),
        ))])
    client.chat.completions.create.side_effect = _side_effect

    result = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert result["failed"] == 1
    assert result["tweets"] == 1
    assert result["signals_inserted"] == 1


@pytest.mark.asyncio
async def test_process_pending_tweets_dup_signal_dedup():
    """같은 (tweet_id, ticker) 재삽입 시 dedup 처리 (unique index)."""
    async with get_session() as session:
        session.add(_make_tweet(300, "x"))
        session.add(SerenitySignal(
            id=str(uuid.uuid4()),
            tweet_id=300, ticker="NBIS", sentiment="bullish", confidence=0.5,
        ))
        await session.commit()

    # tweet 300 은 이미 signal 있어 load_pending 에서 제외 · process 는 0 반환
    client = _fake_client({"signals": [{"ticker": "NBIS", "sentiment": "bullish"}]})
    result = await process_pending_tweets(batch_size=10, concurrency=1, client=client)
    assert result["tweets"] == 0
