"""Blue-Chip 5단계 스크리너 회귀 · Phase E+ · 2026-08-02."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.rulebook.screener import (
    TIER_ENTRY_KRW,
    TIER_PREMIUM_KRW,
    check_market_cap,
    check_sector_pass_through,
)
from backend.services.db import get_session, init_db
from backend.services.models import BlueChipCandidate, BlueChipRun


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(BlueChipCandidate))
        await session.execute(delete(BlueChipRun))
    yield


@pytest_asyncio.fixture
async def client():
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── 단계별 판정 함수 ────────────────────────────────────────────


def test_check_market_cap_premium():
    ok, tier = check_market_cap(TIER_PREMIUM_KRW + 1)
    assert ok and tier == "premium"


def test_check_market_cap_entry():
    ok, tier = check_market_cap(TIER_ENTRY_KRW + 1)
    assert ok and tier == "entry"


def test_check_market_cap_below():
    ok, tier = check_market_cap(TIER_ENTRY_KRW - 1)
    assert not ok and tier == "none"


def test_check_market_cap_none():
    ok, tier = check_market_cap(None)
    assert not ok and tier == "none"


def test_check_sector_pass_through():
    ok, _ = check_sector_pass_through()
    assert ok


# ─── API 응답 shape ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blue_chip_list_empty(client: AsyncClient):
    r = await client.get("/api/v1/rulebook/blue-chip/list")
    assert r.status_code == 200
    j = r.json()
    assert j["run_id"] is None
    assert j["items"] == []


@pytest.mark.asyncio
async def test_blue_chip_list_returns_snapshot(client: AsyncClient):
    """수동으로 candidate 삽입 후 list · 정렬·필터 검증."""
    async with get_session() as session:
        session.add(BlueChipRun(
            run_id="20260802-000000K",
            trigger="test",
            universe_size=2,
            passed_count=1,
            partial_count=1,
        ))
        session.add(BlueChipCandidate(
            run_id="20260802-000000K", ticker="A", name="AAA", market="KOSPI",
            market_cap_krw=15_000_000_000_000, tier="premium",
            revenue_3y_growing=True, net_income_3y_growing=True,
            annual_turnaround=True, monthly_ma5_above=True,
            monthly_ma5_months_above=6,
            conditions_json='{"1":true,"2":true,"3":true,"4":true,"5":true}',
            pass_count=5, overall_pass=True,
        ))
        session.add(BlueChipCandidate(
            run_id="20260802-000000K", ticker="B", name="BBB", market="KOSPI",
            market_cap_krw=6_000_000_000_000, tier="entry",
            revenue_3y_growing=True, net_income_3y_growing=False,
            annual_turnaround=True, monthly_ma5_above=False,
            monthly_ma5_months_above=1,
            conditions_json='{"1":true,"2":true,"3":false,"4":true,"5":false}',
            pass_count=3, overall_pass=False,
            reject_reasons="일부 조건 미달",
        ))
        await session.commit()

    # 기본 min_pass=3 · 두 종목 모두 포함
    r = await client.get("/api/v1/rulebook/blue-chip/list?min_pass=3")
    j = r.json()
    assert j["run_id"] == "20260802-000000K"
    assert len(j["items"]) == 2
    assert j["items"][0]["ticker"] == "A"  # overall_pass 우선 정렬

    # only_overall_pass=true · A만
    r2 = await client.get("/api/v1/rulebook/blue-chip/list?only_overall_pass=true")
    j2 = r2.json()
    assert len(j2["items"]) == 1
    assert j2["items"][0]["ticker"] == "A"


@pytest.mark.asyncio
async def test_blue_chip_detail_404(client: AsyncClient):
    r = await client.get("/api/v1/rulebook/blue-chip/detail/UNKNOWN")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_blue_chip_detail_returns_snapshots(client: AsyncClient):
    async with get_session() as session:
        session.add(BlueChipCandidate(
            run_id="20260802-000000K", ticker="C", name="CCC", market="KOSPI",
            market_cap_krw=15_000_000_000_000, tier="premium",
            revenue_3y_growing=True, net_income_3y_growing=True,
            annual_turnaround=True, monthly_ma5_above=True,
            monthly_ma5_months_above=6,
            conditions_json='{"1":true,"2":true,"3":true,"4":true,"5":true}',
            financial_years="2023,2024,2025",
            annual_yoy_pcts="0.15,0.22,0.18",
            pass_count=5, overall_pass=True,
        ))
        await session.commit()

    r = await client.get("/api/v1/rulebook/blue-chip/detail/C")
    j = r.json()
    assert j["ticker"] == "C"
    assert j["financial_years"] == ["2023", "2024", "2025"]
    assert j["annual_yoy_pcts"] == [0.15, 0.22, 0.18]
    assert isinstance(j["conditions_json"], dict) and len(j["conditions_json"]) >= 1


@pytest.mark.asyncio
async def test_blue_chip_run_requires_auth(monkeypatch, client: AsyncClient):
    """POST /run · SNIPER_API_TOKEN 세팅된 상태에서도 잘못된 헤더면 401."""
    monkeypatch.setenv("SNIPER_API_TOKEN", "test_token_32chars_00000000000000")
    r = await client.post(
        "/api/v1/rulebook/blue-chip/run",
        headers={"X-API-Token": "wrong"},
    )
    assert r.status_code == 401
