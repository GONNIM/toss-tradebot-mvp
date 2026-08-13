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
async def test_toss_account_kr_us_separation(client: AsyncClient, monkeypatch):
    """KR·US 종목 통화별 분리 · '내 계좌' 미러링 (Fable 5 · 2026-08-13)."""
    class _FakeToss:
        def holdings(self, symbol=None):
            return {
                # 상위 집계 · 원본 우선 사용
                "totalPurchaseAmount": {"krw": 1354265, "usd": 2242.71},
                "marketValue": {"krw": 8241516, "amount": 8241516},
                "profitLoss": {"krw": 4644539, "rate": 129.12, "amount": 4644539},
                "items": [
                    # KR 종목 · KRW
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "quantity": "100",
                        "averagePurchasePrice": "13543",
                        "lastPrice": "65750",
                        "currency": "KRW",
                    },
                    # US 종목 · USD
                    {
                        "symbol": "NBIS",
                        "quantity": "0.574",
                        "averagePurchasePrice": "193.23",
                        "lastPrice": "259.20",
                        "currency": "USD",
                    },
                ],
            }
        def buying_power(self, currency="KRW"):
            return {"cashBuyingPower": 1219785 if currency == "KRW" else 3.97}

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
    assert body["ok"] is True
    # KR/US 분리 확인
    assert len(body["kr_holdings"]) == 1
    assert body["kr_holdings"][0]["symbol"] == "005930"
    assert body["kr_holdings"][0]["name"] == "삼성전자"
    assert body["kr_holdings"][0]["currency"] == "KRW"
    assert len(body["us_holdings"]) == 1
    assert body["us_holdings"][0]["symbol"] == "NBIS"
    assert body["us_holdings"][0]["currency"] == "USD"
    # 잔고 필드
    assert body["cash_krw"] == 1219785
    assert body["cash_usd"] == 3.97
    # 총 자산 = 투자 + 주문가능 (사용자 앱 뷰)
    assert body["total_investment_krw"] == 8241516  # 원본 사용
    assert body["total_pnl_krw"] == 4644539  # 원본 사용
    assert body["total_pnl_pct"] == 129.12


@pytest.mark.asyncio
async def test_toss_account_skips_zero_quantity(client: AsyncClient, monkeypatch):
    """quantity=0 items 는 skip (매도 완료 잔재)."""
    class _FakeToss:
        def holdings(self, symbol=None):
            return {"items": [
                {"symbol": "SOLD", "quantity": "0", "averagePurchasePrice": "100", "lastPrice": "110", "currency": "USD"},
                {"symbol": "HELD", "quantity": "1", "averagePurchasePrice": "100", "lastPrice": "110", "currency": "USD"},
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
    all_syms = [h["symbol"] for h in body["us_holdings"]] + [h["symbol"] for h in body["kr_holdings"]]
    assert "HELD" in all_syms
    assert "SOLD" not in all_syms, "qty=0 skip"


@pytest.mark.asyncio
async def test_toss_account_uses_api_values_not_recomputed(client: AsyncClient, monkeypatch):
    """API totalPurchaseAmount/marketValue/profitLoss 원본 그대로 사용 (broker-api-source-of-truth)."""
    class _FakeToss:
        def holdings(self, symbol=None):
            # API 가 반환한 총계 vs 자체 계산 값이 다르면 (환율·수수료) API 우선
            return {
                "totalPurchaseAmount": {"krw": 1000000},
                "marketValue": {"krw": 1200000, "amount": 1200000},
                "profitLoss": {"krw": 200000, "rate": 20.0, "amount": 200000},
                "items": [{"symbol": "005930", "quantity": "10", "averagePurchasePrice": "100000",
                           "lastPrice": "120000", "currency": "KRW"}],
            }
        def buying_power(self, currency="KRW"):
            return {}

    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _FakeToss())
    r = await client.get("/api/v1/dashboard/toss-account", headers={"X-API-Token": TOKEN})
    body = r.json()
    # API 원본 값 그대로 노출
    assert body["total_investment_krw"] == 1200000
    assert body["total_pnl_krw"] == 200000
    assert body["total_pnl_pct"] == 20.0
