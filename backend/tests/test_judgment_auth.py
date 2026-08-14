"""Judgment API 인증 게이트 회귀 (2026-08-14 · auth-gate-is-curl-not-ui).

원칙: 판정 데이터도 개인 논지·전략 · 인증 없이 노출 X.
DoD: curl 로 401 확인 (dashboard 처럼 소급 인증).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import SniperApiAccess, UserJudgment


TOKEN = "judgment_auth_test_token_32chars_00"


@pytest_asyncio.fixture(autouse=True)
async def _clean(monkeypatch):
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as session:
        await session.execute(delete(UserJudgment))
        await session.execute(delete(SniperApiAccess))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_all_judgment_routes_require_auth(client: AsyncClient):
    """6 라우트 전부 인증 없이 401 (curl 401 DoD)."""
    routes = [
        ("GET", "/api/v1/judgments"),
        ("GET", "/api/v1/judgments/baseline"),
        ("POST", "/api/v1/judgments"),
        ("POST", "/api/v1/judgments/1/supersede"),
        ("PATCH", "/api/v1/judgments/1"),
        ("PATCH", "/api/v1/judgments/1/outcome"),
    ]
    for method, path in routes:
        r = await client.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} 인증 없이 노출됨 · status={r.status_code}"


@pytest.mark.asyncio
async def test_judgment_create_with_auth_passes(client: AsyncClient):
    """유효 토큰 → 201 생성."""
    r = await client.post(
        "/api/v1/judgments",
        headers={"X-API-Token": TOKEN},
        json={
            "ticker": "TEST",
            "page_source": "manual",
            "hypothesis_id": "v1",
            "thesis_md": "test",
            "invalidation_price": 10.0,
            "horizon_days": 30,
            "mood": "cool",
            "strategy": "core",
        },
    )
    assert r.status_code == 201, r.text
