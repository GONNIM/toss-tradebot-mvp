"""Serenity Scorer 단위 테스트 · Phase L4 · 2026-08-02.

15원칙 공식 · seed upsert · refresh 파이프라인 검증.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.serenity.aggregators import active_tickers, aggregate_signals
from backend.discovery.serenity.scorer import (
    _csv_from_list,
    _parse_csv,
    compute_serenity_score,
    refresh_all_scores,
    refresh_ticker_score,
    upsert_seed,
)
from backend.services.db import get_session, init_db
from backend.services.models import DiscoverySerenityScore, SerenitySignal


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(DiscoverySerenityScore))
        await session.execute(delete(SerenitySignal))
    yield


# ─── compute_serenity_score · 공식 검증 ────────────────────────


def test_score_all_negatives_zero():
    """빈 dict → 스코어 0 · auto_avoid False."""
    score, avoid = compute_serenity_score({})
    assert score == 0 and avoid is False


def test_score_bottleneck_and_mag7_max():
    """bottleneck 10 × 10 = 100 · mag7 7 × 15 = 105 · 합 205."""
    score, avoid = compute_serenity_score({"bottleneck_score": 10, "mag7_customer_count": 7})
    assert score == 205 and avoid is False


def test_score_gaap_margin_bonus():
    score, _ = compute_serenity_score({"gaap_gross_margin": 61})
    assert score == 30
    score2, _ = compute_serenity_score({"gaap_gross_margin": 60})
    assert score2 == 0  # >60 이 조건 · 60 은 미포함


def test_score_pre_ramp_bonus():
    score, _ = compute_serenity_score({"is_pre_ramp": True})
    assert score == 40


def test_score_contracted_arr_bonus():
    score, _ = compute_serenity_score({"contracted_arr_multiple": 3.1})
    assert score == 50
    score2, _ = compute_serenity_score({"contracted_arr_multiple": 3.0})
    assert score2 == 0


def test_score_institutional_edge():
    score, _ = compute_serenity_score({"institutional_holdings_delta_30d": -1.0})
    assert score == 30


def test_score_atm_penalty_31():
    """atm 31% → -100 penalty · 자동 회피 아직 아님(>40 조건)."""
    score, avoid = compute_serenity_score({"active_atm_pct_of_mc": 31})
    assert score == -100 and avoid is False


def test_score_atm_auto_avoid_41():
    score, avoid = compute_serenity_score({"active_atm_pct_of_mc": 41})
    assert avoid is True


def test_score_anti_pattern_penalty():
    """flag 3개 · -60 penalty · 3개 이상 auto_avoid."""
    score, avoid = compute_serenity_score({"anti_pattern_flags": ["a", "b", "c"]})
    assert score == -60 and avoid is True


def test_score_financing_tier_avoid():
    for tier in ("D", "F"):
        _, avoid = compute_serenity_score({"financing_tier": tier})
        assert avoid is True
    for tier in ("S", "A", "B", "C"):
        _, avoid = compute_serenity_score({"financing_tier": tier})
        assert avoid is False


def test_score_serenity_tier_f_avoid():
    _, avoid = compute_serenity_score({"serenity_tier": "F"})
    assert avoid is True


def test_score_nbis_full_stack_example():
    """관찰 로그 §L NBIS 예시 · 최대 스코어 · not auto_avoid."""
    score, avoid = compute_serenity_score({
        "bottleneck_score": 9,               # 90
        "mag7_customer_count": 5,            # 75
        "gaap_gross_margin": 65,             # 30
        "is_pre_ramp": False,                # 0
        "contracted_arr_multiple": 4.0,      # 50
        "institutional_holdings_delta_30d": -0.5,  # 30
        "financing_tier": "S",
        "serenity_tier": "S",
        "active_atm_pct_of_mc": 0,
        "anti_pattern_flags": [],
    })
    assert score == 275 and avoid is False


def test_score_iren_avoid_example():
    """관찰 로그 §L IREN · 51% ATM + neocloud 리스크 · 반드시 avoid."""
    score, avoid = compute_serenity_score({
        "bottleneck_score": 3,               # 30
        "mag7_customer_count": 1,            # 15
        "financing_tier": "D",
        "serenity_tier": "F",
        "active_atm_pct_of_mc": 51,          # -100 · avoid
        "anti_pattern_flags": ["atm_51pct_overhang", "sbc_1p14b"],  # -40
    })
    assert avoid is True
    # 30 + 15 - 100 - 40 = -95
    assert score == -95


# ─── CSV helpers ─────────────────────────────────────────────────


def test_parse_csv_roundtrip():
    assert _parse_csv("neocloud,ai_power") == ["neocloud", "ai_power"]
    assert _parse_csv(None) == []
    assert _parse_csv("") == []


def test_csv_from_list_roundtrip():
    assert _csv_from_list(["neocloud", "ai_power"]) == "neocloud,ai_power"
    assert _csv_from_list(None) is None
    assert _csv_from_list([]) is None
    assert _csv_from_list(["", " ", "x"]) == "x"


# ─── upsert_seed + refresh ──────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_seed_creates_row():
    await upsert_seed({
        "ticker": "NBIS", "financing_tier": "S", "serenity_tier": "S",
        "domain_tags": ["neocloud"], "anti_pattern_flags": [],
        "bottleneck_score": 9,
    })
    async with get_session() as session:
        row = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == "NBIS")
        )).scalar_one()
    assert row.financing_tier == "S"
    assert row.domain_tags == "neocloud"
    assert row.anti_pattern_flags is None
    assert row.bottleneck_score == 9


@pytest.mark.asyncio
async def test_upsert_seed_updates_existing():
    await upsert_seed({"ticker": "NBIS", "bottleneck_score": 5})
    await upsert_seed({"ticker": "NBIS", "bottleneck_score": 9, "financing_tier": "S"})
    async with get_session() as session:
        row = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == "NBIS")
        )).scalar_one()
    assert row.bottleneck_score == 9
    assert row.financing_tier == "S"


@pytest.mark.asyncio
async def test_refresh_ticker_score_updates_total():
    await upsert_seed({
        "ticker": "NBIS", "bottleneck_score": 9, "mag7_customer_count": 5,
        "financing_tier": "S", "serenity_tier": "S",
    })
    result = await refresh_ticker_score("NBIS")
    assert result["total_score"] == 90 + 75  # 165
    assert result["auto_avoid"] is False


@pytest.mark.asyncio
async def test_refresh_ticker_score_none_when_no_seed():
    assert await refresh_ticker_score("UNKNOWN") is None


@pytest.mark.asyncio
async def test_refresh_all_scores_covers_seed_and_signals():
    """seed 없는데 signal 만 있는 티커는 skipped 로 카운트."""
    await upsert_seed({"ticker": "A", "bottleneck_score": 5})
    async with get_session() as session:
        session.add(SerenitySignal(
            id=str(uuid.uuid4()),
            tweet_id=1, ticker="B", sentiment="bullish", confidence=0.5,
            extracted_at=datetime.utcnow(),
        ))
        await session.commit()

    result = await refresh_all_scores(days=90)
    assert result["scored"] == 1        # A · seed 있음
    assert result["skipped"] == 1        # B · seed 없음
    assert result["targets"] == 2


# ─── aggregate_signals ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_signals_computes_bullish_pct():
    now = datetime.utcnow()
    async with get_session() as session:
        session.add_all([
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=1, ticker="NBIS",
                           sentiment="bullish", confidence=0.9, extracted_at=now),
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=2, ticker="NBIS",
                           sentiment="bullish", confidence=0.8, extracted_at=now),
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=3, ticker="NBIS",
                           sentiment="calibration", confidence=0.4, extracted_at=now),
            # 90일 이전 · 제외
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=4, ticker="NBIS",
                           sentiment="bearish", confidence=0.7,
                           extracted_at=now - timedelta(days=200)),
        ])
        await session.commit()
    agg = await aggregate_signals("NBIS", days=90)
    assert agg["mention_count"] == 3
    assert agg["bullish_count"] == 2
    assert agg["calibration_count"] == 1
    assert agg["bullish_pct"] == round(200 / 3, 2)


@pytest.mark.asyncio
async def test_active_tickers_within_window():
    now = datetime.utcnow()
    async with get_session() as session:
        session.add_all([
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=1, ticker="A",
                           sentiment="bullish", confidence=0.5, extracted_at=now),
            SerenitySignal(id=str(uuid.uuid4()), tweet_id=2, ticker="B",
                           sentiment="bullish", confidence=0.5,
                           extracted_at=now - timedelta(days=200)),
        ])
        await session.commit()
    assert await active_tickers(days=90) == ["A"]
    assert await active_tickers(days=365) == ["A", "B"]
