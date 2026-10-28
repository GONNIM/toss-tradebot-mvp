"""쓰기 API 인증 게이트 (1028-03).

공개 사이트에서 로그인 없이 VIP 설정 · Activist 감시 대상 · Wolf Pack 재계산 · 원칙 검증 확인을
바꿀 수 있었다 → 관리자 토큰 (require_sniper_token) 필수.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import init_db

TOKEN = "write_auth_test_token_32chars_000000"

WRITES = [
    ("PATCH", "/api/v1/meme-watch/vip/config", {"activist": {"enabled": False}}),
    ("PATCH", "/api/v1/meme-watch/activist/universe", {"key": "zz_test"}),
    ("DELETE", "/api/v1/meme-watch/activist/universe/zz_test", None),
    ("POST", "/api/v1/meme-watch/activist/recompute-wolf-pack", None),
    ("POST", "/api/v1/principles/verification/confirm", {"ticker": "000000", "tags": ["x"]}),
]


@pytest_asyncio.fixture(autouse=True)
async def _env(monkeypatch):
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", WRITES)
async def test_write_without_token_is_401(client: AsyncClient, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", WRITES)
async def test_write_with_wrong_token_is_401(client: AsyncClient, method, path, body):
    r = await client.request(method, path, json=body, headers={"X-API-Token": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_principles_confirm_with_token_passes_gate(client: AsyncClient):
    """토큰이 맞으면 인증은 통과하고 본래 검증 (태그 대조) 으로 넘어간다 (401 아님) — 쓰기 부작용 없는 경로."""
    r = await client.post(
        "/api/v1/principles/verification/confirm",
        json={"ticker": "000000", "tags": ["x"]},
        headers={"X-API-Token": TOKEN},
    )
    assert r.status_code != 401


@pytest.mark.asyncio
async def test_reads_stay_public(client: AsyncClient):
    """읽기 API 는 그대로 공개."""
    for path in ("/api/v1/meme-watch/activist/universe", "/api/v1/meme-watch/vip/config"):
        r = await client.get(path)
        assert r.status_code != 401, path
