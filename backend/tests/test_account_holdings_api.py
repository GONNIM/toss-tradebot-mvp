"""1025-08 · GET /api/v1/account/holdings (관리자 전용) · 대시보드 환율 출처."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TOKEN = "account_holdings_test_token_32ch_0"


class _FakeToss:
    def __init__(self, rate="1400"):
        self.rate = rate

    def holdings(self, symbol=None):
        return {"items": [
            {"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW", "quantity": "10",
             "averagePurchasePrice": "60000", "lastPrice": "70000"},
            {"symbol": "WEN", "name": "웬디스", "marketCountry": "US", "currency": "USD", "quantity": "5",
             "averagePurchasePrice": "10", "lastPrice": "12"},
        ]}

    def buying_power(self, currency="KRW"):
        return {}

    def get(self, path, *, params=None, use_account_header=True):
        assert path == "/api/v1/exchange-rate"
        if self.rate is None:
            raise RuntimeError("down")
        return {"rate": self.rate, "validFrom": "2026-10-26T09:00:00+09:00"}


@pytest.fixture
async def client(monkeypatch):
    from backend.services import fx
    from backend.services.db import get_session, init_db
    from backend.services.models import HoldingSnapshot, TossStockCode, UserJudgment

    fx.reset_cache()
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        for m in (HoldingSnapshot, TossStockCode, UserJudgment):
            await s.execute(delete(m))
        s.add(TossStockCode(symbol="WEN", toss_code="US19810527001", source="api", verified=False))
        s.add(UserJudgment(ts=datetime(2026, 9, 1, 1), ticker="WEN", page_source="journal",
                           hypothesis_id="h", thesis_md="t", invalidation_price=8.0))
        s.add(HoldingSnapshot(symbol="WEN", market="US", trade_date=date(2026, 9, 2), kind="candle", close=15.0))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    fx.reset_cache()


@pytest.mark.asyncio
async def test_requires_token(client):
    assert (await client.get("/api/v1/account/holdings")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_holdings_with_facts_links_and_fx(client, monkeypatch):
    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _FakeToss())
    r = await client.get("/api/v1/account/holdings", headers={"X-API-Token": TOKEN})
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["fx_rate"] == 1400.0 and b["fx_source"] == "toss"
    h = {x["symbol"]: x for x in b["holdings"]}
    kr, us = h["005930"], h["WEN"]
    assert kr["market_value_krw"] == 700000 and kr["pnl_pct"] == round(100000 / 600000 * 100, 2)
    assert kr["link"]["kind"] == "order" and kr["link"]["url"].endswith("/A005930/order")
    assert us["market_value"] == 60 and us["market_value_krw"] == 84000 and us["pnl_krw"] == 14000
    assert us["link"]["kind"] == "search"  # 확인 전 미국 종목은 후보 그대로 두지 않음
    assert us["basis_date"] == "2026-09-01" and us["basis_source"] == "journal"
    assert us["peak_close"] == 15.0 and us["from_peak_pct"] == -20.0
    assert us["has_exit_plan"] is True and kr["has_exit_plan"] is False


@pytest.mark.asyncio
async def test_fx_fallback_is_labelled(client, monkeypatch):
    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _FakeToss(rate=None))
    b = (await client.get("/api/v1/account/holdings", headers={"X-API-Token": TOKEN})).json()
    assert b["fx_source"] == "fallback" and b["fx_rate"] == 1330.0


@pytest.mark.asyncio
async def test_toss_failure_is_ok_false(client, monkeypatch):
    class _Down:
        def holdings(self, symbol=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _Down())
    b = (await client.get("/api/v1/account/holdings", headers={"X-API-Token": TOKEN})).json()
    assert b["ok"] is False and "RuntimeError" in b["error_reason"] and b["holdings"] == []


@pytest.mark.asyncio
async def test_dashboard_uses_toss_fx_and_reports_source(client, monkeypatch):
    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _FakeToss())
    b = (await client.get("/api/v1/dashboard/toss-account", headers={"X-API-Token": TOKEN})).json()
    assert b["fx_rate"] == 1400.0 and b["fx_source"] == "toss"
    assert b["us_holdings"][0]["market_value_krw"] == 84000 and b["us_cost_krw"] == 70000


@pytest.mark.asyncio
async def test_positions_plan_uses_toss_fx(client, monkeypatch):
    monkeypatch.setattr("backend.execution.brokers.toss_client.get_toss_client", lambda: _FakeToss())
    b = (await client.get("/api/v1/positions/plan", headers={"X-API-Token": TOKEN})).json()
    wen = [p for p in b["positions"] if p["symbol"] == "WEN"][0]
    assert wen["market_value_krw"] == 84000
