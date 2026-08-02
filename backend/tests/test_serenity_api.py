"""Serenity 공개 read API 회귀 · Phase L6 · 2026-08-02."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

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


# ─── L7 · methodology ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_methodology_returns_text(client: AsyncClient, tmp_path, monkeypatch):
    """submodule 위치를 임시 폴더로 override · methodology.md 응답 검증."""
    ref_dir = tmp_path / "serenity-aleabitoreddit" / "references"
    ref_dir.mkdir(parents=True)
    (ref_dir / "methodology.md").write_text("# 15원칙\ntest body\n", encoding="utf-8")
    monkeypatch.setenv("SERENITY_TRACKER_DIR", str(tmp_path))

    r = await client.get("/api/v1/serenity/methodology")
    assert r.status_code == 200
    j = r.json()
    assert "15원칙" in j["text"]
    assert j["bytes"] > 0
    assert j["source"].endswith("methodology.md")


@pytest.mark.asyncio
async def test_methodology_missing_returns_404(client: AsyncClient, tmp_path, monkeypatch):
    """파일 없으면 404."""
    monkeypatch.setenv("SERENITY_TRACKER_DIR", str(tmp_path))
    # 프로젝트 root vendor 경로에도 실제 파일이 있으면 404 안 나올 수 있어 skip 처리
    from backend.api.routes.serenity import _resolve_methodology_path
    if _resolve_methodology_path() is not None:
        pytest.skip("vendor/serenity-tracker methodology.md 실제 존재 · env override 무효화")
    r = await client.get("/api/v1/serenity/methodology")
    assert r.status_code == 404


# ─── L7 · backtest/summary ───────────────────────────────────────


@pytest.mark.asyncio
async def test_backtest_summary_empty(client: AsyncClient):
    r = await client.get("/api/v1/serenity/backtest/summary")
    assert r.status_code == 200
    j = r.json()
    assert j["total_backtests"] == 0
    assert j["overall"]["count"] == 0
    assert j["by_sentiment"] == [] and j["by_financing_tier"] == []
    assert j["top_tickers_60d"] == []


@pytest.mark.asyncio
async def test_backtest_summary_buckets_by_sentiment_and_tier(client: AsyncClient):
    """seed + backtest 2건 · sentiment/tier bucket · top ticker 정렬 검증."""
    await _seed()
    now = datetime.utcnow()
    async with get_session() as session:
        # NBIS bullish signal 의 id 를 얻기 위해 다시 조회
        sig_nbis = (await session.execute(
            select(SerenitySignal).where(SerenitySignal.ticker == "NBIS")
        )).scalar_one()
        sig_iren = (await session.execute(
            select(SerenitySignal).where(SerenitySignal.ticker == "IREN")
        )).scalar_one()

        session.add_all([
            SerenityBacktest(
                id=str(uuid.uuid4()), signal_id=sig_nbis.id, ticker="NBIS",
                signal_date="2026-06-01", price_at_signal=100.0,
                return_5d=1.0, return_10d=2.0, return_30d=10.0, return_60d=20.0, return_180d=50.0,
                computed_at=now,
            ),
            SerenityBacktest(
                id=str(uuid.uuid4()), signal_id=sig_iren.id, ticker="IREN",
                signal_date="2026-06-01", price_at_signal=100.0,
                return_5d=-1.0, return_10d=-3.0, return_30d=-15.0, return_60d=-30.0, return_180d=-40.0,
                computed_at=now,
            ),
        ])
        await session.commit()

    r = await client.get("/api/v1/serenity/backtest/summary")
    j = r.json()
    assert j["total_backtests"] == 2
    assert j["overall"]["avg_return_60d"] == round((20.0 + -30.0) / 2, 2)

    sent = {b["key"]: b for b in j["by_sentiment"]}
    assert sent["bullish"]["avg_return_60d"] == 20.0
    assert sent["bearish"]["avg_return_60d"] == -30.0

    tier = {b["key"]: b for b in j["by_financing_tier"]}
    assert tier["S"]["count"] == 1 and tier["D"]["count"] == 1

    top = j["top_tickers_60d"]
    assert top[0]["key"] == "NBIS"
    assert top[-1]["key"] == "IREN"
