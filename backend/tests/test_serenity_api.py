"""Serenity 공개 read API 회귀 · Phase L6 · 2026-08-02."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import (
    DiscoverySerenityScore,
    SerenityBacktest,
    SerenitySignal,
    SerenityTweet,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenityBacktest))
        await session.execute(delete(SerenitySignal))
        await session.execute(delete(SerenityTweet))
        await session.execute(delete(DiscoverySerenityScore))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _seed():
    now = datetime.utcnow()
    tw = SerenityTweet(
        id=str(uuid.uuid4()),
        tweet_id=111, url="https://x.com/aleabitoreddit/status/111",
        posted_at=now, text="test $NBIS bullish",
    )
    sig = SerenitySignal(
        id=str(uuid.uuid4()), tweet_id=111, ticker="NBIS",
        sentiment="bullish", thesis_type="new_bottleneck",
        evidence_type="earnings", confidence=0.9,
        extracted_reasoning="test reason", extracted_at=now,
    )
    sig2 = SerenitySignal(
        id=str(uuid.uuid4()), tweet_id=111, ticker="IREN",
        sentiment="bearish", confidence=0.7,
        extracted_at=now,
    )
    score_ok = DiscoverySerenityScore(
        ticker="NBIS", financing_tier="S", serenity_tier="S",
        domain_tags="neocloud", anti_pattern_flags=None,
        total_score=250, auto_avoid=False,
    )
    score_avoid = DiscoverySerenityScore(
        ticker="IREN", financing_tier="D", serenity_tier="F",
        domain_tags="neocloud",
        anti_pattern_flags="atm_51pct_overhang,sbc_1p14b",
        total_score=-95, auto_avoid=True,
    )
    async with get_session() as session:
        session.add_all([tw, sig, sig2, score_ok, score_avoid])
        await session.commit()


# ─── summary ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_empty(client: AsyncClient):
    r = await client.get("/api/v1/serenity/summary")
    assert r.status_code == 200
    j = r.json()
    assert j["tweets"] == 0 and j["signals"] == 0
    assert j["tickers_scored"] == 0 and j["tickers_auto_avoid"] == 0


@pytest.mark.asyncio
async def test_summary_reflects_seed(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/summary")).json()
    assert j["tweets"] == 1
    assert j["signals"] == 2
    assert j["tickers_scored"] == 2
    assert j["tickers_auto_avoid"] == 1


# ─── signals ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signals_returns_with_tweet_context(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/signals?days=30")).json()
    assert len(j) == 2
    for item in j:
        assert item["tweet_text"] == "test $NBIS bullish"
        assert item["tweet_url"].endswith("/111")


@pytest.mark.asyncio
async def test_signals_filter_by_sentiment(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/signals?sentiment=bullish&days=30")).json()
    assert len(j) == 1 and j[0]["ticker"] == "NBIS"


@pytest.mark.asyncio
async def test_signals_filter_by_ticker(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/signals?ticker=iren&days=30")).json()
    assert len(j) == 1 and j[0]["sentiment"] == "bearish"


# ─── tickers ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tickers_sorted_by_score_desc(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/tickers")).json()
    assert [t["ticker"] for t in j] == ["NBIS", "IREN"]
    assert j[0]["total_score"] == 250
    assert j[0]["domain_tags"] == ["neocloud"]
    assert j[1]["auto_avoid"] is True
    assert j[1]["anti_pattern_flags"] == ["atm_51pct_overhang", "sbc_1p14b"]


@pytest.mark.asyncio
async def test_tickers_exclude_avoid(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/tickers?include_avoid=false")).json()
    assert [t["ticker"] for t in j] == ["NBIS"]


@pytest.mark.asyncio
async def test_ticker_detail_404(client: AsyncClient):
    r = await client.get("/api/v1/serenity/tickers/UNKNOWN")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ticker_detail_returns_score_and_signals(client: AsyncClient):
    await _seed()
    j = (await client.get("/api/v1/serenity/tickers/NBIS")).json()
    assert j["ticker"] == "NBIS"
    assert j["score"]["total_score"] == 250
    assert len(j["recent_signals"]) == 1
    assert set(j["backtest_avg"].keys()) == {
        "return_5d", "return_10d", "return_30d", "return_60d", "return_180d",
    }
