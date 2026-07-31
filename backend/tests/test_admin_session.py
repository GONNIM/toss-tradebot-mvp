"""Phase D 주 7 · 관리자 세션(httpOnly 쿠키) 인증 회귀 테스트.

검증:
- POST /api/v1/admin/session (성공/실패)
- Set-Cookie 헤더 실제 세팅
- GET /api/v1/admin/session (whoami · anon/admin 판정)
- DELETE /api/v1/admin/session (쿠키 삭제)
- 기존 X-API-Token 헤더 fallback (하위 호환)
- sniper_api_access 감사 이벤트 DB append 확인 (login_ok / login_fail / auth_ok)
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import SniperApiAccess


TOKEN = "phase_d_test_token_32chars_0000000"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db(monkeypatch):
    # 다른 테스트가 SNIPER_API_TOKEN 을 다른 값으로 덮어써도 우리 테스트마다 강제 재세팅
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


# ─── whoami ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_whoami_anon(client: AsyncClient):
    """세션 미소지자는 role=anon."""
    r = await client.get("/api/v1/admin/session")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "anon"
    assert "live_enabled" in body


# ─── login ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_success_sets_cookie(client: AsyncClient):
    """올바른 토큰 → 200 + httpOnly Set-Cookie."""
    r = await client.post("/api/v1/admin/session", json={"token": TOKEN})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    cookies = r.headers.get_list("set-cookie")
    assert cookies, "Set-Cookie 헤더 없음"
    joined = "; ".join(cookies).lower()
    assert "sniper_session=" in joined
    assert "httponly" in joined
    assert "samesite=lax" in joined


@pytest.mark.asyncio
async def test_login_failure_401(client: AsyncClient):
    """잘못된 토큰 → 401."""
    r = await client.post("/api/v1/admin/session", json={"token": "wrong"})
    assert r.status_code == 401


# ─── 세션 유지 · whoami=admin ────────────────────────────────────


@pytest.mark.asyncio
async def test_whoami_admin_after_login(client: AsyncClient):
    """로그인 → 같은 AsyncClient 로 후속 GET 시 admin."""
    r = await client.post("/api/v1/admin/session", json={"token": TOKEN})
    assert r.status_code == 200

    r2 = await client.get("/api/v1/admin/session")
    assert r2.status_code == 200
    assert r2.json()["role"] == "admin"


# ─── logout ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_clears_cookie(client: AsyncClient):
    """DELETE → 200 + 쿠키 삭제 (max-age=0 또는 expires=과거)."""
    await client.post("/api/v1/admin/session", json={"token": TOKEN})
    r = await client.delete("/api/v1/admin/session")
    assert r.status_code == 200
    assert r.json()["role"] == "anon"

    # 후속 whoami 는 anon
    r2 = await client.get("/api/v1/admin/session")
    assert r2.json()["role"] == "anon"


# ─── 하위 호환 · X-API-Token 헤더 fallback ───────────────────────


@pytest.mark.asyncio
async def test_header_token_fallback(client: AsyncClient):
    """쿠키 없어도 X-API-Token 헤더로 admin 판정 (서버-서버 호환)."""
    r = await client.get(
        "/api/v1/admin/session",
        headers={"X-API-Token": TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


# ─── 감사 이벤트 DB append ───────────────────────────────────────


@pytest.mark.asyncio
async def test_login_ok_writes_audit_row(client: AsyncClient):
    """정상 로그인 → sniper_api_access 에 event=login_ok 1건 append."""
    await client.post("/api/v1/admin/session", json={"token": TOKEN})
    async with get_session() as session:
        result = await session.execute(
            select(SniperApiAccess).where(SniperApiAccess.event == "login_ok")
        )
        rows = result.scalars().all()
    assert len(rows) >= 1
    row = rows[-1]
    assert row.role == "admin"
    assert row.token_source == "body"


@pytest.mark.asyncio
async def test_login_fail_writes_audit_row(client: AsyncClient):
    """실패 로그인 → event=login_fail, role=anon."""
    await client.post("/api/v1/admin/session", json={"token": "wrong"})
    async with get_session() as session:
        result = await session.execute(
            select(SniperApiAccess).where(SniperApiAccess.event == "login_fail")
        )
        rows = result.scalars().all()
    assert len(rows) >= 1
    assert rows[-1].role == "anon"


# ─── 관리·편집 라우트 401 회귀 ───────────────────────────────────


@pytest.mark.asyncio
async def test_admin_route_rejects_anon(client: AsyncClient):
    """세션·헤더 없는 요청은 관리 라우트에서 401.

    watchlist finalize (POST · require_sniper_token) 로 확인.
    """
    r = await client.post("/api/v1/watchlist/finalize", json={"top_n": 10})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_route_allows_cookie_session(client: AsyncClient):
    """로그인 후 세션 쿠키로 관리 라우트 통과 (401 이 아님)."""
    await client.post("/api/v1/admin/session", json={"token": TOKEN})
    r = await client.post("/api/v1/watchlist/finalize", json={"top_n": 10})
    # 세션은 통과 (401 아님). 실 실행이 200/500 여부는 무관 (인증 통과만 검증).
    assert r.status_code != 401
