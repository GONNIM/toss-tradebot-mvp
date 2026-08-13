"""dashboard 인증 게이트 회귀 · 2026-08-13 Fable 5 지시.

DoD: /api/v1/dashboard/toss-account 는 인증 없이 절대 응답하지 않는다.
    프론트 숨김은 인증 아님 · curl 로 401 확인이 배포 차단 게이트.

원칙: 실 계좌 잔고·보유종목·평균가는 URL 하나로 노출되면 안 됨.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import SniperApiAccess


TOKEN = "dashboard_test_token_32chars_00000000"


@pytest_asyncio.fixture(autouse=True)
async def _clean(monkeypatch):
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SniperApiAccess))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_toss_account_requires_auth(client: AsyncClient):
    """토큰 없이 /toss-account 호출 → 401 (실 계좌 노출 방지)."""
    r = await client.get("/api/v1/dashboard/toss-account")
    assert r.status_code == 401, (
        "인증 없이 실 계좌 스냅샷이 노출되면 안 됨. "
        "Fable 5 원칙: 프론트 숨김은 인증 아님."
    )


@pytest.mark.asyncio
async def test_toss_account_rejects_bad_token(client: AsyncClient):
    """잘못된 토큰 → 401."""
    r = await client.get(
        "/api/v1/dashboard/toss-account",
        headers={"X-API-Token": "wrong_token_xxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_summary_requires_auth(client: AsyncClient):
    """기존 /dashboard/ 도 인증 필수 (2026-08-13 확장)."""
    r = await client.get("/api/v1/dashboard/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_toss_account_valid_token_passes_auth(client: AsyncClient, monkeypatch):
    """유효 토큰 → 인증 통과 (200 with ok=false 도 통과 · 401 아니면 됨).

    Toss API 실제 호출은 실패해도 (테스트 환경 · 토큰 없음)
    응답은 200 + ok=false + error_reason 이어야 함 (Fable 5 정직 UX).
    """
    r = await client.get(
        "/api/v1/dashboard/toss-account",
        headers={"X-API-Token": TOKEN},
    )
    # 인증 통과 · 200 (ok=false 가능 · 401·403·500 은 절대 아님)
    assert r.status_code == 200, f"인증 통과 후 200 기대 · 실제 {r.status_code} · body={r.text[:200]}"
    body = r.json()
    # Toss API 실제 실패 시 정직한 응답
    assert "ok" in body
    assert "fetched_at" in body
    assert "market_open" in body
    assert "price_source" in body
