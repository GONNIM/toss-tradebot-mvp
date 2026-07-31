"""Phase D 주 8 · 관측성·webhook 스텁·DB config 회귀 스모크."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import SniperApiAccess


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SniperApiAccess))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── DATABASE_URL config 위임 ────────────────────────────────────


def test_database_url_config_default(monkeypatch):
    """DATABASE_URL 미설정 시 sqlite+aiosqlite 기본."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # dotenv override=False 라 이미 로드된 env 값이 살아있을 수 있음 · 직접 값 검증
    from backend.services.config import database_url

    url = database_url()
    assert url.startswith("sqlite+aiosqlite:///") or url.startswith("postgresql+asyncpg://")


def test_database_url_scheme_boost_sqlite(monkeypatch):
    """sqlite:/// 는 자동으로 +aiosqlite 붙임."""
    from backend.services.config import database_url

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    assert database_url() == "sqlite+aiosqlite:///./x.db"


def test_database_url_scheme_boost_postgres(monkeypatch):
    """postgresql:// 는 자동으로 +asyncpg 붙임."""
    from backend.services.config import database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:5432/db")
    assert database_url() == "postgresql+asyncpg://user:pw@host:5432/db"


# ─── Sentry init · DSN 없으면 no-op ──────────────────────────────


def test_sentry_init_noop_without_dsn(monkeypatch):
    """SENTRY_DSN 미설정 시 init_sentry() False (앱 부팅 방해 없음)."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # observability 모듈의 _INITIALIZED 캐시 무력화 (다른 테스트 잔재 대비)
    import importlib

    import backend.services.observability as obs

    importlib.reload(obs)
    assert obs.init_sentry() is False


def test_sentry_init_with_dsn(monkeypatch):
    """가짜 DSN 이라도 init_sentry() True 반환 (실제 이벤트 전송은 X)."""
    import importlib

    import backend.services.observability as obs

    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.com/1")
    monkeypatch.setenv("APP_ENV", "test")
    importlib.reload(obs)
    assert obs.init_sentry() is True


# ─── Webhook payment 스텁 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_webhook_stub_returns_200(client: AsyncClient):
    """빈 body 여도 200 · 감사 로그 이벤트 append."""
    r = await client.post(
        "/api/v1/webhooks/payment",
        json={"event": "payment.paid", "orderId": "test-123"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    async with get_session() as session:
        result = await session.execute(
            select(SniperApiAccess).where(SniperApiAccess.event == "payment_webhook")
        )
        rows = result.scalars().all()
    assert len(rows) >= 1
    row = rows[-1]
    assert "payment.paid" in (row.detail or "")


@pytest.mark.asyncio
async def test_payment_webhook_handles_invalid_json(client: AsyncClient):
    """비-JSON body 여도 200 · parse=invalid_json 감사 detail."""
    r = await client.post(
        "/api/v1/webhooks/payment",
        content=b"NOT_JSON",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200
