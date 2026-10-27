"""Crazy · Moonshot 조회 라우트 회귀 (1025-03 · B1).

- 조회 전부 로그인 필수 (401 · 토큰이면 200)
- 목록 경로 307 없이 200
- 결과 요약 20건 미만이면 중앙값 없이 건수만
- Super Signal 5분 잡 기본 끔 · /sniper/status 노출
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.services.db import get_session, init_db
from backend.services.models import CrazyPick, MoonshotPick, SniperApiAccess
from backend.services.outcomes import summarize

TOKEN = "lab_picks_auth_test_token_32chars_0"
HDR = {"X-API-Token": TOKEN}


@pytest_asyncio.fixture(autouse=True)
async def _clean(monkeypatch):
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as session:
        await session.execute(delete(CrazyPick))
        await session.execute(delete(MoonshotPick))
        await session.execute(delete(SniperApiAccess))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


ROUTES = [
    "/api/v1/crazy?limit=3",
    "/api/v1/crazy/history?days=7",
    "/api/v1/crazy/summary",
    "/api/v1/crazy/AAPL",
    "/api/v1/moonshot?limit=3",
    "/api/v1/moonshot/history?days=7",
    "/api/v1/moonshot/summary",
    "/api/v1/moonshot/AAPL",
]


@pytest.mark.asyncio
async def test_all_pick_routes_require_auth(client: AsyncClient):
    for path in ROUTES:
        r = await client.get(path)
        assert r.status_code == 401, f"{path} 인증 없이 노출됨 · status={r.status_code}"


@pytest.mark.asyncio
async def test_list_routes_ok_without_redirect(client: AsyncClient):
    for path in ("/api/v1/crazy?limit=3", "/api/v1/moonshot?limit=3"):
        r = await client.get(path, headers=HDR)
        assert r.status_code == 200, f"{path} status={r.status_code}"
        assert r.json() == []


@pytest.mark.asyncio
async def test_summary_hides_median_below_20(client: AsyncClient):
    async with get_session() as session:
        for i in range(19):
            session.add(CrazyPick(pick_date="2026-10-01", rank=i + 1, ticker=f"T{i}", perf_1w=0.01 * i))
        await session.commit()
    r = await client.get("/api/v1/crazy/summary", headers=HDR)
    assert r.status_code == 200
    assert r.json() == {"1w": {"n": 19, "median": None}, "1m": {"n": 0, "median": None}}


@pytest.mark.asyncio
async def test_summary_shows_median_from_20(client: AsyncClient):
    async with get_session() as session:
        for i in range(20):
            session.add(MoonshotPick(pick_date="2026-10-01", rank=i + 1, ticker=f"M{i}", perf_1d=float(i)))
        await session.commit()
    r = await client.get("/api/v1/moonshot/summary", headers=HDR)
    body = r.json()
    assert body["1d"] == {"n": 20, "median": 9.5}
    assert body["3d"] == {"n": 0, "median": None}


def test_summarize_skips_none():
    class Row:
        def __init__(self, v):
            self.perf = v
    rows = [Row(None)] * 5 + [Row(1.0)] * 20
    assert summarize(rows, {"x": "perf"}) == {"x": {"n": 20, "median": 1.0}}


@pytest.mark.asyncio
async def test_super_signal_off_by_default(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("SUPER_SIGNAL_ENABLED", raising=False)
    r = await client.get("/api/v1/sniper/status")
    assert r.status_code == 200
    assert r.json()["super_signal_enabled"] is False
    monkeypatch.setenv("SUPER_SIGNAL_ENABLED", "true")
    r = await client.get("/api/v1/sniper/status")
    assert r.json()["super_signal_enabled"] is True
