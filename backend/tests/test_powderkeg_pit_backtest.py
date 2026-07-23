"""P2-2 · PIT 층화 백테스트 테스트.

- as-of 재무 조회 · release_date <= as_of 최신 선택
- 상폐 종목이 이벤트 시점엔 살아있는 케이스
- pit_evaluate 6조건 · 통과·탈락 시나리오
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.backtest import (
    _as_of_financials,
    _as_of_shareholder,
    pit_evaluate,
)
from backend.powderkeg.collectors.ftc_big_biz import refresh_from_seed
from backend.services.db import get_session, init_db
from backend.services.models import (
    BigBusinessGroup,
    FinancialSnapshot,
    MajorShareholder,
    PowderKegEvent,
)


TICKER = "999001"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(FinancialSnapshot))
        await session.execute(delete(MajorShareholder))
        await session.execute(delete(BigBusinessGroup))
        await session.execute(delete(PowderKegEvent))
    yield


async def _seed_pit_ideal(ticker: str = TICKER, is_delisted: bool = False,
                          delisted_dt: datetime | None = None):
    """이벤트 시점 (2024-06-15) 기준 화약고 통과하도록 시딩 (Piotroski 6+ 위해 개선 트렌드).
       release_date 는 최신 재무 = 2024-03-15 (< 2024-06-15)."""
    release_2024 = datetime(2024, 3, 15, tzinfo=timezone.utc)
    release_2023 = datetime(2023, 3, 15, tzinfo=timezone.utc)
    release_2022 = datetime(2022, 3, 15, tzinfo=timezone.utc)
    # ref, release, ni, cfo, total_assets, total_debt, curr_a, curr_l, revenue, gp
    yearly = [
        ("2023-12-31", release_2024, 4_000_000_000, 5_000_000_000, 22_000_000_000, 800_000_000,
         14_000_000_000, 2_500_000_000, 35_000_000_000, 18_000_000_000),
        ("2022-12-31", release_2023, 3_000_000_000, 3_500_000_000, 20_000_000_000, 1_000_000_000,
         12_000_000_000, 3_000_000_000, 30_000_000_000, 14_000_000_000),
        ("2021-12-31", release_2022, 2_500_000_000, 2_800_000_000, 19_000_000_000, 1_200_000_000,
         11_000_000_000, 3_000_000_000, 28_000_000_000, 12_000_000_000),
    ]
    async with get_session() as session:
        for ref, rel, ni, cfo, ta, td, ca, cl, rev, gp in yearly:
            session.add(FinancialSnapshot(
                ticker=ticker, corp_code="00000001",
                reference_date=ref, report_code="11011",
                release_date=rel,
                cash_and_equivalents=8_000_000_000,
                short_term_investments=2_000_000_000,
                total_debt=td,
                total_equity=15_000_000_000,
                retained_earnings=10_000_000_000,
                total_assets=ta,
                current_assets=ca,
                current_liabilities=cl,
                revenue=rev,
                gross_profit=gp,
                operating_income=ni,
                net_income=ni,
                interest_income=400_000_000,
                cash_flow_from_operations=cfo,
                shares_outstanding=1_000_000,
                audit_opinion="적정",
                is_delisted=is_delisted,
                delisted_at=delisted_dt,
            ))
        session.add(MajorShareholder(
            ticker=ticker,
            reference_date="2024-03-15",
            release_date=release_2024,
            major_pct=0.42, related_pct=0.05, treasury_pct=0.02,
        ))
    # 대기업집단 · TRADE_TICKER 는 미포함 (통과)
    await refresh_from_seed(2024)


# ─────────────────────────────────────────────────────────────
# as-of 조회 · release_date <= as_of 필터
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_as_of_financials_returns_only_before_asof():
    await _seed_pit_ideal()
    # as_of = 2024-06-15 · 2024/2023/2022 재무 모두 이전 → 3개
    result = await _as_of_financials(TICKER, date(2024, 6, 15))
    assert len(result) == 3
    # as_of = 2023-06-15 · 2023/2022 재무만 (2024는 아직 release_date 미도래)
    result2 = await _as_of_financials(TICKER, date(2023, 6, 15))
    assert len(result2) == 2


@pytest.mark.asyncio
async def test_as_of_shareholder_returns_only_before_asof():
    await _seed_pit_ideal()
    r = await _as_of_shareholder(TICKER, date(2024, 6, 15))
    assert r is not None
    assert r.major_pct == 0.42
    # 2024-03-15 이전엔 최대주주 데이터 없음
    r2 = await _as_of_shareholder(TICKER, date(2024, 1, 1))
    assert r2 is None


@pytest.mark.asyncio
async def test_as_of_financials_empty_when_asof_before_any():
    await _seed_pit_ideal()
    result = await _as_of_financials(TICKER, date(2020, 1, 1))
    assert result == []


# ─────────────────────────────────────────────────────────────
# pit_evaluate · 6조건 판정
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pit_evaluate_passes_when_all_6_ok():
    await _seed_pit_ideal()
    passed, meta = await pit_evaluate(TICKER, date(2024, 6, 15))
    assert passed is True, f"meta={meta}"
    for k in ("3_owner", "5_audit", "6_cash_reality", "7_op_profit", "8_fscore", "4_not_big_biz"):
        assert meta["cond"][k] is True
    assert set(meta["unmeasured"]) == {"1_pbr", "9_adv60", "10_no_bad_history"}


@pytest.mark.asyncio
async def test_pit_evaluate_fails_when_no_financial():
    passed, meta = await pit_evaluate("XXXXXX", date(2024, 6, 15))
    assert passed is False
    assert meta["reason"] == "no_financial_data"


@pytest.mark.asyncio
async def test_pit_evaluate_uses_as_of_not_latest():
    """이벤트 시점(2023-06-15)에 2년 재무만 존재 → F-Score 계산 가능 · PIT 통과 유지."""
    await _seed_pit_ideal()
    passed, meta = await pit_evaluate(TICKER, date(2023, 6, 15))
    # 재무 2년만 · 감사 2년 · 최대주주 없음 (2024-03-15 이후) → 실패
    assert passed is False
    assert meta["cond"]["3_owner"] is None


@pytest.mark.asyncio
async def test_pit_evaluate_delisted_ticker_still_valid_before_delisting():
    """상폐 종목 · 이벤트 시점엔 살아있음 → PIT 정상 평가."""
    await _seed_pit_ideal(
        is_delisted=True,
        delisted_dt=datetime(2025, 12, 1, tzinfo=timezone.utc),
    )
    # 이벤트 시점 2024-06-15 · 상폐 전 → 평가 가능
    passed, meta = await pit_evaluate(TICKER, date(2024, 6, 15))
    assert passed is True


@pytest.mark.asyncio
async def test_pit_evaluate_low_owner_fails_condition_3():
    async with get_session() as session:
        release = datetime(2024, 3, 15, tzinfo=timezone.utc)
        for ref, ni in [
            ("2023-12-31", 3_000_000_000),
            ("2022-12-31", 2_500_000_000),
            ("2021-12-31", 2_000_000_000),
        ]:
            session.add(FinancialSnapshot(
                ticker=TICKER, corp_code="00000001",
                reference_date=ref, report_code="11011",
                release_date=release,
                cash_and_equivalents=8_000_000_000,
                short_term_investments=2_000_000_000,
                total_debt=1_000_000_000,
                total_equity=15_000_000_000, retained_earnings=10_000_000_000,
                total_assets=22_000_000_000,
                current_assets=14_000_000_000, current_liabilities=2_500_000_000,
                revenue=35_000_000_000, gross_profit=18_000_000_000,
                operating_income=ni, net_income=ni,
                interest_income=400_000_000,
                cash_flow_from_operations=5_000_000_000,
                shares_outstanding=1_000_000,
                audit_opinion="적정",
            ))
        session.add(MajorShareholder(
            ticker=TICKER, reference_date="2024-03-15", release_date=release,
            major_pct=0.15, related_pct=0.05,   # 20% (임계 40 미달)
        ))
    await refresh_from_seed(2024)

    passed, meta = await pit_evaluate(TICKER, date(2024, 6, 15))
    assert passed is False
    assert meta["cond"]["3_owner"] is False
    assert "3_owner" in meta["reason"]
