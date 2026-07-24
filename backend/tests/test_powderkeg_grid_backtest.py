"""P2-2b · Grid Search API + thresholds 반영 정합 테스트."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.backtest import pit_evaluate, run_stratified_backtest
from backend.powderkeg.collectors.ftc_big_biz import refresh_from_seed
from backend.services.db import get_session, init_db
from backend.services.models import (
    BigBusinessGroup,
    FinancialSnapshot,
    MajorShareholder,
    PowderKegEvent,
)


TICKER = "998001"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(FinancialSnapshot))
        await session.execute(delete(MajorShareholder))
        await session.execute(delete(BigBusinessGroup))
        await session.execute(delete(PowderKegEvent))
    yield


async def _seed_marginal_ticker(ticker: str = TICKER, owner_pct: float = 0.35):
    """owner 35% · 기존 임계 40 미만 · 완화 30 통과."""
    release = datetime(2024, 3, 15, tzinfo=timezone.utc)
    async with get_session() as session:
        for ref, ni, cfo, ta, td in [
            ("2023-12-31", 3_000_000_000, 3_500_000_000, 22_000_000_000, 1_000_000_000),
            ("2022-12-31", 2_500_000_000, 2_800_000_000, 20_000_000_000, 1_100_000_000),
            ("2021-12-31", 2_000_000_000, 2_500_000_000, 19_000_000_000, 1_200_000_000),
        ]:
            session.add(FinancialSnapshot(
                ticker=ticker, corp_code="00000002",
                reference_date=ref, report_code="11011",
                release_date=release,
                cash_and_equivalents=8_000_000_000,
                short_term_investments=2_000_000_000,
                total_debt=td, total_equity=15_000_000_000,
                retained_earnings=10_000_000_000, total_assets=ta,
                current_assets=14_000_000_000, current_liabilities=2_500_000_000,
                revenue=35_000_000_000, gross_profit=18_000_000_000,
                operating_income=ni, net_income=ni,
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
# thresholds 전달 정합
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pit_evaluate_owner_relax_by_thresholds():
    """owner 35% 시딩 · 기본 40 실패 → 완화 30 통과."""
    await _seed_marginal_ticker(owner_pct=0.35)
    _, meta_default = await pit_evaluate(TICKER, date(2024, 6, 15))
    assert meta_default["cond"]["3_owner"] is False
    _, meta_relax = await pit_evaluate(
        TICKER, date(2024, 6, 15),
        thresholds={"major_shareholder_pct_min": 0.30},
    )
    assert meta_relax["cond"]["3_owner"] is True


@pytest.mark.asyncio
async def test_pit_evaluate_fscore_relax_by_thresholds():
    """F-Score 임계 완화 override 반영."""
    await _seed_marginal_ticker(owner_pct=0.50)   # owner 는 통과 · fscore 만 관찰
    # 기본 fscore_min=6
    _, meta_default = await pit_evaluate(TICKER, date(2024, 6, 15))
    fscore_pass_default = meta_default["cond"]["8_fscore"]
    # 완화 fscore_min=3 · 항상 통과 기대
    _, meta_relax = await pit_evaluate(
        TICKER, date(2024, 6, 15),
        thresholds={"piotroski_f_score_min": 3},
    )
    fscore_pass_relax = meta_relax["cond"]["8_fscore"]
    # 완화가 더 관대해야 함 · pass_default→False 이면 relax→True 이어야
    if fscore_pass_default is False:
        assert fscore_pass_relax is True
    else:
        assert fscore_pass_relax is True


# ─────────────────────────────────────────────────────────────
# run_stratified_backtest thresholds 반영
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stratified_backtest_thresholds_propagate_to_pit():
    """thresholds 완화가 pit_passed 증가로 반영."""
    await _seed_marginal_ticker(owner_pct=0.35)
    async with get_session() as session:
        session.add(PowderKegEvent(
            ticker=TICKER, event_type="A3",
            source="test", title="test event",
            release_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
        ))

    r_default = await run_stratified_backtest("A3", stratum="powderkeg_pit")
    r_relax = await run_stratified_backtest(
        "A3", stratum="powderkeg_pit",
        thresholds={"major_shareholder_pct_min": 0.30, "piotroski_f_score_min": 4},
    )

    # 완화 조합의 pit_passed 는 기본보다 크거나 같아야 함
    assert r_relax["pit_meta"]["pit_passed"] >= r_default["pit_meta"]["pit_passed"]
    # 이 케이스는 이벤트 1개 · 완화로 통과 → 1
    assert r_relax["pit_meta"]["pit_passed"] >= 1


# ─────────────────────────────────────────────────────────────
# Grid API 스키마 (인증 우회 · Depends override)
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grid_api_returns_result_per_combination():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api.auth import require_sniper_token

    await _seed_marginal_ticker()
    async with get_session() as session:
        session.add(PowderKegEvent(
            ticker=TICKER, event_type="A3",
            source="test", title="test event",
            release_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
        ))

    grid = [
        {"piotroski_f_score_min": 6, "major_shareholder_pct_min": 0.40},   # 기본
        {"piotroski_f_score_min": 4, "major_shareholder_pct_min": 0.30},   # 완화
    ]

    # 인증 dependency override
    app.dependency_overrides[require_sniper_token] = lambda: None
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/powderkeg/backtest/A3/grid",
                json={"grid": grid},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["event_type"] == "A3"
            assert body["grid_size"] == 2
            assert len(body["results"]) == 2
            for res in body["results"]:
                assert "thresholds" in res
                assert "pit_meta" in res
                assert "aggregate" in res
                assert "decision" in res
    finally:
        app.dependency_overrides.clear()
