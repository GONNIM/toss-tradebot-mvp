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


# ─── 실 응답 파싱 회귀 (2026-08-13 · items[] · dict 구조) ─────────────


@pytest.mark.asyncio
async def test_toss_account_parses_items_dict_response(client: AsyncClient, monkeypatch):
    """holdings() 가 dict{items:[...]} · buying_power cashBuyingPower · lastPrice 응답 파싱.

    실 사고 재현: 이전 구현이 응답을 list 로 순회 → holdings=[] 렌더 사고.
    docs/analysis/toss-api-survey.md §1.5 실 구조 반영 검증.
    """
    class _FakeToss:
        def holdings(self, symbol=None):
            return {
                "totalPurchaseAmount": {"krw": 0, "usd": 100.0},
                "items": [
                    {
                        "symbol": "NBIS",
                        "quantity": "0.574",
                        "averagePurchasePrice": "193.23",
                        "lastPrice": "259.20",
                        "currency": "USD",
                    },
                    {
                        "symbol": "MU",
                        "quantity": "0.163",
                        "averagePurchasePrice": "911.29",
                        "lastPrice": "911.29",
                        "currency": "USD",
                    },
                ],
            }

        def buying_power(self, currency="KRW"):
            return {"cashBuyingPower": 12345.67 if currency == "KRW" else 89.10}

    monkeypatch.setattr(
        "backend.execution.brokers.toss_client.get_toss_client",
        lambda: _FakeToss(),
    )

    r = await client.get(
        "/api/v1/dashboard/toss-account",
        headers={"X-API-Token": TOKEN},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, f"파싱 성공 시 ok=true · body={body}"
    assert len(body["holdings"]) == 2, "items 2개 파싱"
    nbis = next(h for h in body["holdings"] if h["symbol"] == "NBIS")
    assert nbis["qty"] == 0.574
    assert nbis["avg_price"] == 193.23
    assert nbis["current_price"] == 259.20
    assert body["balance_krw"] == 12345.67
    assert body["balance_usd"] == 89.10


@pytest.mark.asyncio
async def test_toss_account_skips_zero_quantity(client: AsyncClient, monkeypatch):
    """quantity=0 items 는 skip (매도 완료 잔재)."""
    class _FakeToss:
        def holdings(self, symbol=None):
            return {"items": [
                {"symbol": "SOLD", "quantity": "0", "averagePurchasePrice": "100", "lastPrice": "110"},
                {"symbol": "HELD", "quantity": "1", "averagePurchasePrice": "100", "lastPrice": "110"},
            ]}
        def buying_power(self, currency="KRW"):
            return {}

    monkeypatch.setattr(
        "backend.execution.brokers.toss_client.get_toss_client",
        lambda: _FakeToss(),
    )
    r = await client.get(
        "/api/v1/dashboard/toss-account",
        headers={"X-API-Token": TOKEN},
    )
    body = r.json()
    symbols = [h["symbol"] for h in body["holdings"]]
    assert "HELD" in symbols
    assert "SOLD" not in symbols, "qty=0 skip"
