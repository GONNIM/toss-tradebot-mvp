"""Rulebook API 스모크 · Phase E · 2026-08-02.

R:R 계산기·분포·물타기 감지 로그 최소 회귀.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import UserJudgment


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(UserJudgment))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── R:R 계산기 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rr_calc_long_verdict_recommended(client: AsyncClient):
    """Long · R:R 6.0 (=(13000-10000)/(10000-9500)) → 권장."""
    r = await client.get(
        "/api/v1/rulebook/rr-calc",
        params={"entry": 10000, "invalidation": 9500, "target": 13000},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["direction"] == "long"
    assert abs(j["rr_ratio"] - 6.0) < 0.001
    assert "권장" in j["verdict"]


@pytest.mark.asyncio
async def test_rr_calc_short_direction(client: AsyncClient):
    """Short · target < entry < invalidation."""
    r = await client.get(
        "/api/v1/rulebook/rr-calc",
        params={"entry": 10000, "invalidation": 10500, "target": 9000},
    )
    j = r.json()
    assert j["direction"] == "short"
    assert abs(j["rr_ratio"] - 2.0) < 0.001


@pytest.mark.asyncio
async def test_rr_calc_invalid_relation(client: AsyncClient):
    """entry > target > invalidation 등 · invalid direction."""
    r = await client.get(
        "/api/v1/rulebook/rr-calc",
        params={"entry": 10000, "invalidation": 9500, "target": 9800},
    )
    j = r.json()
    assert j["direction"] == "invalid"
    assert j["rr_ratio"] is None


@pytest.mark.asyncio
async def test_rr_calc_rejects_non_positive(client: AsyncClient):
    r = await client.get(
        "/api/v1/rulebook/rr-calc",
        params={"entry": -1, "invalidation": 100, "target": 200},
    )
    assert r.status_code == 400


# ─── R:R 분포 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rr_stats_empty(client: AsyncClient):
    """판정 없을 때 · computable_count 0 · buckets 3구간."""
    r = await client.get("/api/v1/rulebook/rr-stats?days=90")
    j = r.json()
    assert j["computable_count"] == 0
    assert j["avg_rr_ratio"] is None
    assert len(j["buckets"]) == 3


@pytest.mark.asyncio
async def test_rr_stats_bucketing(client: AsyncClient):
    """entry·target·inv 있는 판정만 집계."""
    async with get_session() as session:
        session.add_all([
            UserJudgment(
                ticker="A", page_source="manual", hypothesis_id="h1",
                thesis_md="t", invalidation_price=9500, target_price=13000,
                entry_price=10000, horizon_days=7, mood="cool", market_regime="bull",
            ),  # R:R = 6.0 (bucket ≥2)
            UserJudgment(
                ticker="B", page_source="manual", hypothesis_id="h2",
                thesis_md="t", invalidation_price=9000, target_price=10500,
                entry_price=10000, horizon_days=7, mood="cool", market_regime="bull",
            ),  # R:R = 0.5 (bucket <1)
            UserJudgment(
                ticker="C", page_source="manual", hypothesis_id="h3",
                thesis_md="t", invalidation_price=9000, target_price=11500,
                entry_price=10000, horizon_days=7, mood="cool", market_regime="bull",
            ),  # R:R = 1.5 (bucket 1~2)
        ])
        await session.commit()

    r = await client.get("/api/v1/rulebook/rr-stats?days=90")
    j = r.json()
    assert j["computable_count"] == 3
    assert j["target_hit_count"] == 1
    assert j["target_hit_rate"] == 1 / 3
    bucket_map = {b["label"]: b["count"] for b in j["buckets"]}
    assert bucket_map["R:R ≥ 2"] == 1
    assert bucket_map["1 ≤ R:R < 2"] == 1
    assert bucket_map["R:R < 1"] == 1


# ─── 물타기 감지 로그 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidation_hits_empty(client: AsyncClient):
    r = await client.get("/api/v1/rulebook/invalidation-hits")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_invalidation_hits_returns_marked_rows(client: AsyncClient):
    from datetime import datetime

    async with get_session() as session:
        # 이탈 감지된 판정 (invalidation_hit_ts != NULL)
        session.add(UserJudgment(
            ticker="MARK", page_source="powderkeg", hypothesis_id="pk-v2",
            thesis_md="t", invalidation_price=9500, horizon_days=7,
            mood="revenge", market_regime="bear",
            invalidation_hit_ts=datetime.utcnow(),
            invalidation_hit_low=9200.0,
        ))
        # 이탈 없는 판정 (검색에서 제외되어야 함)
        session.add(UserJudgment(
            ticker="OK", page_source="watchlist", hypothesis_id="wl",
            thesis_md="t", invalidation_price=9500, horizon_days=7,
            mood="cool", market_regime="bull",
        ))
        await session.commit()

    r = await client.get("/api/v1/rulebook/invalidation-hits?days=90")
    j = r.json()
    assert len(j) == 1
    assert j[0]["ticker"] == "MARK"
    assert j[0]["invalidation_hit_low"] == 9200.0


# ─── Baseline 확장 필드 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_includes_rr_and_invalidation_fields(client: AsyncClient):
    """Baseline 응답에 avg_rr_ratio / rr_computable_count / invalidation_hit_* 포함."""
    r = await client.get("/api/v1/judgments/baseline?days=90")
    j = r.json()
    assert "avg_rr_ratio" in j
    assert "rr_computable_count" in j
    assert "invalidation_hit_count" in j
    assert "invalidation_hit_rate" in j


@pytest.mark.asyncio
async def test_judgment_create_persists_entry_price(client: AsyncClient):
    """POST 판정 시 entry_price 저장·응답 반영."""
    payload = {
        "ticker": "005930",
        "page_source": "manual",
        "hypothesis_id": "test",
        "thesis_md": "R:R persistence check",
        "invalidation_price": 70000,
        "target_price": 100000,
        "entry_price": 80000,
        "horizon_days": 7,
        "mood": "cool",
    }
    r = await client.post("/api/v1/judgments", json=payload)
    assert r.status_code == 201
    assert r.json()["entry_price"] == 80000
