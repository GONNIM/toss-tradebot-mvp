"""PATCH /judgments/{id} · 명시 null vs 미전송 구분 (2026-08-14 사고 대응).

배경: 부분 업데이트에서 target_price 를 비울 방법이 없었음.
     "target_price 미전송 = 유지" 와 "target_price=null = 비움" 이 같게 처리됨.

Fix: payload.model_dump(exclude_unset=True) · 명시 전송된 필드만 갱신 · null 포함.
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
async def _clean(monkeypatch):
    monkeypatch.setenv("SNIPER_API_TOKEN", "testtoken32chars_00000000000000")
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


async def _create(client: AsyncClient, target_price: float | None = 25.0) -> int:
    r = await client.post("/api/v1/judgments", headers={"X-API-Token": "testtoken32chars_00000000000000"}, json={
        "ticker": "WEN",
        "page_source": "test",
        "hypothesis_id": "test-v1",
        "thesis_md": "test",
        "invalidation_price": 8.0,
        "target_price": target_price,
        "horizon_days": 30,
        "mood": "cool",
        "strategy": "event",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_patch_target_null_clears_field(client: AsyncClient):
    """target_price: null 명시 전송 → 실제 null 저장 (소원 이관 · [× 비우기] 지원)."""
    jid = await _create(client, target_price=25.0)

    r = await client.patch(f"/api/v1/judgments/{jid}", headers={"X-API-Token": "testtoken32chars_00000000000000"}, json={
        "target_price": None,
        "change_note": "소원으로 이관",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_price"] is None, "명시 null → 실제 null 저장 실패"


@pytest.mark.asyncio
async def test_patch_target_omitted_keeps_field(client: AsyncClient):
    """target_price 미전송 → 기존 값 유지 (null 명시와 구분)."""
    jid = await _create(client, target_price=25.0)

    # target_price 미전송 · horizon_days 만 변경
    r = await client.patch(f"/api/v1/judgments/{jid}", headers={"X-API-Token": "testtoken32chars_00000000000000"}, json={
        "horizon_days": 60,
        "change_note": "horizon 만 변경",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_price"] == 25.0, "미전송 → 유지 실패"
    assert body["horizon_days"] == 60


@pytest.mark.asyncio
async def test_patch_qty_null_clears_field(client: AsyncClient):
    """qty null 도 동일 원칙 · 트랑셰 미지정으로 되돌리기."""
    r = await client.post("/api/v1/judgments", headers={"X-API-Token": "testtoken32chars_00000000000000"}, json={
        "ticker": "TTD",
        "page_source": "test",
        "hypothesis_id": "test-v1",
        "thesis_md": "test",
        "invalidation_price": 10.0,
        "horizon_days": 30,
        "mood": "cool",
        "strategy": "swing",
        "qty": 5.0,
    })
    jid = r.json()["id"]

    r = await client.patch(f"/api/v1/judgments/{jid}", headers={"X-API-Token": "testtoken32chars_00000000000000"}, json={
        "qty": None,
        "change_note": "트랑셰 미지정으로",
    })
    assert r.status_code == 200
    assert r.json()["qty"] is None
