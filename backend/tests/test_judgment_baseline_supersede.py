"""Baseline·KPI 집계 · superseded 필터 회귀 (Fable 5 · 2026-08-14).

원칙: supersede 생성 시 어떤 KPI 도 개선되지 않아야 함 (부풀림 방지).
활성 판정만 baseline 카운트 · rejection criteria · mood/page_source 분포.
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
async def _clean():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(UserJudgment))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _create(client: AsyncClient, ticker: str, page_source: str = "manual",
                  mood: str = "cool", strategy: str = "core") -> int:
    r = await client.post("/api/v1/judgments", json={
        "ticker": ticker,
        "page_source": page_source,
        "hypothesis_id": "test-v1",
        "thesis_md": "test thesis",
        "invalidation_price": 100.0,
        "target_price": 200.0,
        "horizon_days": 30,
        "mood": mood,
        "strategy": strategy,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_baseline_excludes_superseded(client: AsyncClient):
    """supersede 생성 후 KPI 가 개선되지 않아야 함 (모든 집계 필터)."""
    # 3건 저장 (전부 manual · cool · core)
    id1 = await _create(client, "TICK1")
    id2 = await _create(client, "TICK2")
    id3 = await _create(client, "TICK3")

    r = await client.get("/api/v1/judgments/baseline?days=90")
    before = r.json()
    assert before["total_count"] == 3
    assert before["mood_distribution"]["cool"] == 3
    assert before["page_source_distribution"]["manual"] == 3

    # 신규 판정 저장 + id1 supersede
    id_new = await _create(client, "TICK1", page_source="positions")
    r = await client.post(f"/api/v1/judgments/{id1}/supersede", json={
        "by_id": id_new,
        "reason": "test supersede",
    })
    assert r.status_code == 200

    # supersede 후 baseline · 활성 판정만 (id_new + id2 + id3 = 3건 · id1 제외)
    r = await client.get("/api/v1/judgments/baseline?days=90")
    after = r.json()
    # supersede 로 진행률 개선 없음 · 활성 3건 그대로
    assert after["total_count"] == 3, (
        f"supersede 후 total_count 증가 X (활성 유지) · 실제 {after['total_count']}"
    )
    # 지금 활성: id_new(positions) + id2(manual) + id3(manual) → manual 2 · positions 1
    assert after["page_source_distribution"].get("manual") == 2
    assert after["page_source_distribution"].get("positions") == 1
    # id1 (mood=cool) 이 sup 됐지만 나머지 3건 다 cool
    assert after["mood_distribution"]["cool"] == 3


@pytest.mark.asyncio
async def test_baseline_win_rate_excludes_superseded(client: AsyncClient):
    """승률 계산에서 superseded 판정 제외."""
    id1 = await _create(client, "TICK1")

    # id1 에 result_at_horizon 을 직접 세팅 (승리 · 10%)
    async with get_session() as session:
        row = await session.get(UserJudgment, id1)
        row.result_at_horizon = 0.10
        await session.commit()

    r = await client.get("/api/v1/judgments/baseline?days=90")
    before = r.json()
    assert before["computed_count"] == 1
    assert before["win_rate"] == 1.0  # 1/1

    # id1 supersede · 승률 판정 제외 되어야 함
    id_new = await _create(client, "TICK1")
    await client.post(f"/api/v1/judgments/{id1}/supersede", json={
        "by_id": id_new, "reason": "test",
    })

    r = await client.get("/api/v1/judgments/baseline?days=90")
    after = r.json()
    assert after["computed_count"] == 0, "superseded 판정의 outcome 은 승률 집계에서 제외"
    assert after["win_rate"] is None
