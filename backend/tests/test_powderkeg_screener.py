"""P7-2d 스크리너 오케스트레이터 통합 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.collectors.ftc_big_biz import refresh_from_seed
from backend.powderkeg.screener import (
    ScreenerThresholds,
    run_screener,
    screen_ticker,
)
from backend.services.db import get_session, init_db
from backend.services.models import (
    FinancialSnapshot,
    KrxMarketSnapshot,
    MajorShareholder,
    PowderKegKrxIssue,
    PowderKegList,
)


TRADE_TICKER = "111111"       # 대기업집단 미포함 가상 종목
FAKE_KOSPI = "005930"         # 삼성전자 · 대기업집단


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(FinancialSnapshot))
        await session.execute(delete(KrxMarketSnapshot))
        await session.execute(delete(MajorShareholder))
        await session.execute(delete(PowderKegList))
        await session.execute(delete(PowderKegKrxIssue))
    yield


async def _seed_krx_snapshot_clean(tickers: list[str], snapshot_date: str = "2026-07-23"):
    """P4-5 · KRX 스냅샷 존재하지만 대상 티커는 미지정 상태 시뮬레이션 (c10=True 유도).

    실 스크리너는 스냅샷 미수집 시 c10=None → passed_all=False 로 판정하므로,
    통과 테스트에는 스냅샷 존재 + 대상 티커 미지정을 함께 시딩해야 함.
    """
    async with get_session() as session:
        # baseline · 다른 티커 하나를 관리종목으로 넣어 스냅샷 존재 확증
        session.add(PowderKegKrxIssue(
            ticker="900000", name="TEST_ADMIN_ONLY", kind="admin",
            reason="시가총액 미달", designation_date="2026-07-21",
            snapshot_date=snapshot_date,
        ))


async def _seed_ideal_powder_keg(ticker: str = TRADE_TICKER):
    """11 조건 전부 통과하도록 시딩 (v1.46 · 규모 필터 3000억 반영).
       F-Score 4+ 위해 개선 트렌드 유지 · 매출 4000억 · 영업익 400억."""
    now = datetime.now(tz=timezone.utc)
    # ref_date, ni(=op_inc), cfo, total_assets, total_debt, curr_a, curr_l, revenue, gp, shares
    yearly_data = [
        ("2026-12-31", 40_000_000_000, 50_000_000_000, 220_000_000_000, 8_000_000_000,
         140_000_000_000, 25_000_000_000, 400_000_000_000, 180_000_000_000, 10_000_000),
        ("2025-12-31", 30_000_000_000, 35_000_000_000, 200_000_000_000, 10_000_000_000,
         120_000_000_000, 30_000_000_000, 350_000_000_000, 140_000_000_000, 10_000_000),
        ("2024-12-31", 25_000_000_000, 28_000_000_000, 190_000_000_000, 12_000_000_000,
         110_000_000_000, 30_000_000_000, 320_000_000_000, 120_000_000_000, 10_000_000),
    ]
    async with get_session() as session:
        for ref_date, ni, cfo, ta, td, ca, cl, rev, gp, sh in yearly_data:
            session.add(FinancialSnapshot(
                ticker=ticker, corp_code="00000001",
                reference_date=ref_date, report_code="11011",
                release_date=now,
                cash_and_equivalents=80_000_000_000,
                short_term_investments=20_000_000_000,
                total_debt=td,
                total_equity=15_000_000_000,
                retained_earnings=10_000_000_000,
                total_assets=ta,
                current_assets=ca,
                current_liabilities=cl,
                revenue=rev,
                gross_profit=gp,
                operating_income=ni,   # 흑자 · Piotroski §1
                net_income=ni,
                interest_income=4_000_000_000,
                cash_flow_from_operations=cfo,
                shares_outstanding=sh,
                audit_opinion="적정",
            ))
        # KRX 스냅샷 · PBR 0.3 · 시총 2000억 · ADV 5억 (v1.46 · 규모 반영)
        session.add(KrxMarketSnapshot(
            ticker=ticker, snapshot_date="2026-07-15",
            market="KOSDAQ", close_price=20000,
            market_cap=200_000_000_000,   # 순현금 920억 / 2000억 = 46%
            pbr=0.3, avg_daily_amount_60d=500_000_000,
        ))
        # 최대주주 45% · 특수관계인 포함
        session.add(MajorShareholder(
            ticker=ticker, reference_date="2026-06-30", release_date=now,
            major_pct=0.35, related_pct=0.10, treasury_pct=0.02,
        ))
    # 공정위 seed 로드 (조건 4 · TRADE_TICKER 는 미포함)
    await refresh_from_seed(2026)
    # P4-5 · KRX 스냅샷 (조건 10 · 대상 티커는 리스트에 없음 · c10=True)
    await _seed_krx_snapshot_clean([ticker])


@pytest.mark.asyncio
async def test_screen_ticker_passes_all_10_conditions():
    await _seed_ideal_powder_keg()
    r = await screen_ticker(TRADE_TICKER)
    assert r.status == "passed", f"reject_reasons={r.reject_reasons} conds={r.conditions}"
    assert r.passed_all is True
    # name 은 LiveTapeUniverse 에 seed 되어 있지 않지만 · fallback None 허용 (KRX 스냅샷도 name 없음)
    # 실 프로덕션 · KRX 스냅샷 name 은 collector 갱신으로 채워짐
    # 서브스코어 채워짐
    assert r.pbr == 0.3
    assert r.net_cash_ratio == pytest.approx(0.46)
    assert r.owner_pct == pytest.approx(0.45)
    assert r.piotroski_f_score is not None
    assert r.piotroski_f_score >= 6


@pytest.mark.asyncio
async def test_screen_rejects_high_pbr():
    await _seed_ideal_powder_keg()
    async with get_session() as session:
        row = (await session.execute(
            select(KrxMarketSnapshot).where(KrxMarketSnapshot.ticker == TRADE_TICKER)
        )).scalar_one()
        row.pbr = 0.8    # >= 0.5
    r = await screen_ticker(TRADE_TICKER)
    assert r.status == "rejected"
    assert not r.conditions["1_pbr"]
    assert any("pbr" in x for x in r.reject_reasons)


@pytest.mark.asyncio
async def test_screen_rejects_big_biz():
    """삼성전자 · 대기업집단 소속 · 조건 4 실패."""
    await _seed_ideal_powder_keg(FAKE_KOSPI)
    r = await screen_ticker(FAKE_KOSPI)
    # 다른 조건 통과해도 대기업집단이라 rejected
    assert not r.conditions["4_not_big_biz"]
    assert "big_biz_group" in r.reject_reasons


@pytest.mark.asyncio
async def test_screen_cash_suspect_when_interest_zero():
    await _seed_ideal_powder_keg()
    async with get_session() as session:
        latest = (await session.execute(
            select(FinancialSnapshot).where(FinancialSnapshot.ticker == TRADE_TICKER)
            .order_by(FinancialSnapshot.reference_date.desc()).limit(1)
        )).scalar_one()
        latest.interest_income = 0    # 현금 100억인데 이자 0
    r = await screen_ticker(TRADE_TICKER)
    assert r.status == "cash_suspect"
    assert not r.conditions["6_cash_reality"]


@pytest.mark.asyncio
async def test_screen_rejects_low_owner_pct():
    await _seed_ideal_powder_keg()
    async with get_session() as session:
        holder = (await session.execute(select(MajorShareholder))).scalar_one()
        holder.major_pct = 0.20
        holder.related_pct = 0.05   # 합 25% < 40%
    r = await screen_ticker(TRADE_TICKER)
    assert not r.conditions["3_owner_pct"]


@pytest.mark.asyncio
async def test_screen_rejects_low_fscore():
    """F-Score 데이터 부족 · 낮은 점수."""
    await _seed_ideal_powder_keg()
    async with get_session() as session:
        # 전년도 2건 모두 삭제 → F-Score 미계산 (fin_all < 2)
        await session.execute(
            delete(FinancialSnapshot).where(
                FinancialSnapshot.ticker == TRADE_TICKER,
                FinancialSnapshot.reference_date != "2026-12-31",
            )
        )
    r = await screen_ticker(TRADE_TICKER)
    assert not r.conditions["8_fscore"]
    # F-Score 는 None 이거나 낮음
    assert (r.piotroski_f_score or 0) < 6


@pytest.mark.asyncio
async def test_run_screener_batch():
    """3 종목 batch · 결과 집계."""
    # ticker A · 통과 예상
    await _seed_ideal_powder_keg("A11111")
    # ticker B · PBR 실패
    await _seed_ideal_powder_keg("B22222")
    async with get_session() as session:
        r = (await session.execute(
            select(KrxMarketSnapshot).where(KrxMarketSnapshot.ticker == "B22222")
        )).scalar_one()
        r.pbr = 1.5
    # ticker C · 대기업집단 (조건 4 실패)
    await _seed_ideal_powder_keg(FAKE_KOSPI)

    stats = await run_screener(["A11111", "B22222", FAKE_KOSPI])
    assert stats["total"] == 3
    assert stats["passed"] == 1
    assert stats["rejected"] == 2

    # PowderKegList 저장 확인
    async with get_session() as session:
        rows = (await session.execute(
            select(PowderKegList).where(PowderKegList.run_id == stats["run_id"])
        )).scalars().all()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_screen_no_data_rejects_gracefully():
    """데이터 자체 없음 · 예외 아닌 rejected."""
    await refresh_from_seed(2026)
    r = await screen_ticker("999999")
    assert r.status == "rejected"
    assert "no_financial_data" in r.reject_reasons or "no_market_data" in r.reject_reasons
