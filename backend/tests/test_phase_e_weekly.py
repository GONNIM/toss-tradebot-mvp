"""Phase E · Weekly Insights 초안 API 회귀."""
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


@pytest.mark.asyncio
async def test_weekly_insights_empty_returns_shape(client: AsyncClient):
    """판정 0건이어도 200 + 필드 완비."""
    r = await client.get("/api/v1/insights/weekly?days=7")
    assert r.status_code == 200
    body = r.json()
    assert "week_label" in body and body["week_label"].startswith("20")
    assert body["judgment_stats"]["total"] == 0
    assert isinstance(body["summary_bullets"], list) and len(body["summary_bullets"]) >= 1
    assert isinstance(body["tier_events"], list)


@pytest.mark.asyncio
async def test_weekly_insights_win_rate_bullet(client: AsyncClient):
    """outcome 계산된 판정이 있으면 win_rate/avg_return 요약 bullet 포함."""
    async with get_session() as session:
        session.add_all([
            UserJudgment(
                ticker="005930",
                page_source="watchlist",
                hypothesis_id="watchlist-manual-add",
                thesis_md="test",
                invalidation_price=70000,
                horizon_days=7,
                mood="neutral",
                market_regime="bull",
                result_at_horizon=0.05,
            ),
            UserJudgment(
                ticker="000660",
                page_source="powderkeg",
                hypothesis_id="powderkeg-v2-lock",
                thesis_md="test",
                invalidation_price=100000,
                horizon_days=7,
                mood="cool",
                market_regime="bull",
                result_at_horizon=-0.02,
            ),
        ])
        await session.commit()

    r = await client.get("/api/v1/insights/weekly?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["judgment_stats"]["total"] == 2
    assert body["judgment_stats"]["computed"] == 2
    assert body["judgment_stats"]["win_rate"] == 0.5
    assert any("승률" in b for b in body["summary_bullets"])


@pytest.mark.asyncio
async def test_weekly_insights_hot_state_warning(client: AsyncClient):
    """revenge/fomo mood 판정 있으면 경고 bullet 포함."""
    async with get_session() as session:
        session.add(UserJudgment(
            ticker="123456",
            page_source="sniper",
            hypothesis_id="sniper-enable-toggle",
            thesis_md="test",
            invalidation_price=1000,
            horizon_days=7,
            mood="revenge",
            market_regime="choppy",
        ))
        await session.commit()

    r = await client.get("/api/v1/insights/weekly?days=30")
    body = r.json()
    assert any("hot state" in b or "revenge" in b for b in body["summary_bullets"])
