"""P2-2c · 역설계 · list_event_features_by_car + API 정합 테스트."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.backtest import (
    _extract_event_features,
    _feature_stats,
    list_event_features_by_car,
)
from backend.powderkeg.collectors.ftc_big_biz import refresh_from_seed
from backend.services.db import get_session, init_db
from backend.services.models import (
    BigBusinessGroup,
    FinancialSnapshot,
    MajorShareholder,
    PowderKegEvent,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(FinancialSnapshot))
        await session.execute(delete(MajorShareholder))
        await session.execute(delete(BigBusinessGroup))
        await session.execute(delete(PowderKegEvent))
    yield


async def _seed_ticker_with_features(
    ticker: str, owner_pct: float = 0.50,
    ni: int = 3_000_000_000, cash: int = 8_000_000_000,
):
    release = datetime(2024, 3, 15, tzinfo=timezone.utc)
    async with get_session() as session:
        for ref, ni_y, cfo, ta, td in [
            ("2023-12-31", ni, ni + 500_000_000, 22_000_000_000, 800_000_000),
            ("2022-12-31", ni - 500_000_000, ni, 20_000_000_000, 1_000_000_000),
            ("2021-12-31", ni - 1_000_000_000, ni - 500_000_000, 19_000_000_000, 1_200_000_000),
        ]:
            session.add(FinancialSnapshot(
                ticker=ticker, corp_code="00000003",
                reference_date=ref, report_code="11011",
                release_date=release,
                cash_and_equivalents=cash,
                short_term_investments=2_000_000_000,
                total_debt=td, total_equity=15_000_000_000,
                retained_earnings=10_000_000_000, total_assets=ta,
                current_assets=14_000_000_000, current_liabilities=2_500_000_000,
                revenue=35_000_000_000, gross_profit=18_000_000_000,
                operating_income=ni_y, net_income=ni_y,
                interest_income=400_000_000,
                cash_flow_from_operations=cfo,
                shares_outstanding=1_000_000,
                audit_opinion="적정",
            ))
        session.add(MajorShareholder(
            ticker=ticker, reference_date="2024-03-15", release_date=release,
            major_pct=owner_pct - 0.05, related_pct=0.05,
        ))
    await refresh_from_seed(2024)


# ─────────────────────────────────────────────────────────────
# _extract_event_features · as-of 특성 추출
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_features_returns_all_keys():
    await _seed_ticker_with_features("990001", owner_pct=0.60)
    f = await _extract_event_features("990001", date(2024, 6, 15))
    assert f["owner_pct"] == pytest.approx(0.60)
    assert f["audit_ok_2y"] is True
    assert f["op_profit_years_positive"] == 3
    assert f["piotroski_f_score"] is not None
    assert f["is_delisted"] is False
    assert f["cash_current"] == 10_000_000_000


@pytest.mark.asyncio
async def test_extract_features_missing_when_no_financial():
    f = await _extract_event_features("999999", date(2024, 6, 15))
    assert f == {"missing": "no_financial_data"}


# ─────────────────────────────────────────────────────────────
# _feature_stats · 평균·중앙값
# ─────────────────────────────────────────────────────────────


def test_feature_stats_numeric():
    rows = [
        {"features": {"owner_pct": 0.5}},
        {"features": {"owner_pct": 0.7}},
        {"features": {"owner_pct": 0.6}},
    ]
    s = _feature_stats(rows, "owner_pct")
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(0.6)
    assert s["median"] == pytest.approx(0.6)


def test_feature_stats_bool_counted_as_ones():
    rows = [
        {"features": {"audit_ok_2y": True}},
        {"features": {"audit_ok_2y": False}},
        {"features": {"audit_ok_2y": True}},
    ]
    s = _feature_stats(rows, "audit_ok_2y")
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(2 / 3)


def test_feature_stats_skips_none():
    rows = [
        {"features": {"owner_pct": None}},
        {"features": {"owner_pct": 0.4}},
    ]
    s = _feature_stats(rows, "owner_pct")
    assert s["n"] == 1
    assert s["mean"] == pytest.approx(0.4)


# ─────────────────────────────────────────────────────────────
# list_event_features_by_car · CAR sort · top/bottom 추출
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_event_features_sorts_by_car_and_extracts():
    """3 이벤트 · CAR 상위 1 · 하위 1 추출 · 특성 매트릭스 반영."""
    for t, own in [("111111", 0.70), ("222222", 0.50), ("333333", 0.30)]:
        await _seed_ticker_with_features(t, owner_pct=own)

    async with get_session() as session:
        for t in ("111111", "222222", "333333"):
            session.add(PowderKegEvent(
                ticker=t, event_type="A3",
                source="test", title="test",
                release_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            ))

    # compute_event_return 을 mock · ticker 별로 다른 CAR 반환
    from backend.powderkeg import backtest as bt

    async def _mock_ret(ticker, d, windows):
        car_map = {"111111": 0.50, "222222": 0.10, "333333": -0.30}
        from types import SimpleNamespace
        return SimpleNamespace(per_window_returns={"12m": car_map.get(ticker)})

    with patch.object(bt, "compute_event_return", new=_mock_ret):
        result = await list_event_features_by_car("A3", top_pct=0.34, window="12m")

    assert result["events_with_return"] == 3
    assert result["top_n"] == 1
    assert result["bottom_n"] == 1
    assert result["top_events"][0]["ticker"] == "111111"    # 최고 CAR
    assert result["bottom_events"][0]["ticker"] == "333333"  # 최저 CAR
    # feature_summary owner_pct · top 70 · bottom 30
    fs = result["feature_summary"]["owner_pct"]
    assert fs["top"]["mean"] == pytest.approx(0.70)
    assert fs["bottom"]["mean"] == pytest.approx(0.30)
    assert fs["diff_mean"] == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_list_event_features_empty_when_no_events():
    result = await list_event_features_by_car("A3", top_pct=0.20)
    assert result["events_with_return"] == 0
    assert result["top_events"] == []
    assert result["bottom_events"] == []


# ─────────────────────────────────────────────────────────────
# API · GET /backtest/{event_type}/reverse-engineer
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reverse_engineer_api_schema():
    from fastapi.testclient import TestClient
    from backend.api.main import app

    await _seed_ticker_with_features("444444", owner_pct=0.55)
    async with get_session() as session:
        session.add(PowderKegEvent(
            ticker="444444", event_type="A3",
            source="test", title="test",
            release_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
        ))

    from backend.powderkeg import backtest as bt

    async def _mock_ret(ticker, d, windows):
        from types import SimpleNamespace
        return SimpleNamespace(per_window_returns={"12m": 0.15})

    with patch.object(bt, "compute_event_return", new=_mock_ret):
        with TestClient(app) as client:
            r = client.get("/api/v1/powderkeg/backtest/A3/reverse-engineer?top_pct=0.5&window=12m")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["event_type"] == "A3"
            assert body["window"] == "12m"
            assert body["top_pct"] == 0.5
            assert body["events_with_return"] == 1
            assert "feature_summary" in body
            assert "unmeasured_conditions" in body
