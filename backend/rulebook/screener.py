"""5단계 우량주 스크리너 · Phase E+ · 2026-08-02.

강의 원칙 1 (docs/operations/principles/johnma-8-fundamentals.md):
    1. 시가총액 ≥ 5조 (premium tier ≥ 10조)
    2. 업종 미래 · 자동 통과 (Q2=모든 섹터)
    3. 매출·순이익 3년 연속 증가
    4. 연봉 3년 연평균 증가 (턴어라운드 · Q3=A)
    5. 월봉 5MA 위 3개월+ 유지

Powderkeg 스크리너 패턴 미러 (backend/powderkeg/screener.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.discovery.data_sources.krx_price.monthly import (
    ma5_persistence,
    three_year_yoy,
)
from backend.services.db import get_session
from backend.services.models import (
    BlueChipCandidate,
    BlueChipRun,
    FinancialSnapshot,
    KrxMarketSnapshot,
)

logger = logging.getLogger(__name__)

# 시총 tier 임계 (Q1=C · 2tier)
TIER_ENTRY_KRW = 5_000_000_000_000     # 5조
TIER_PREMIUM_KRW = 10_000_000_000_000  # 10조

# 동시 스캔 종목 수 (DART/pykrx rate 보호)
CONCURRENCY = 4


# ─── 단계별 판정 함수 ────────────────────────────────────────────


def check_market_cap(market_cap: Optional[float]) -> tuple[bool, str]:
    """단계 1 · 시총 ≥ 5조. tier 라벨 반환."""
    if market_cap is None:
        return (False, "none")
    if market_cap >= TIER_PREMIUM_KRW:
        return (True, "premium")
    if market_cap >= TIER_ENTRY_KRW:
        return (True, "entry")
    return (False, "none")


def check_sector_pass_through() -> tuple[bool, str]:
    """단계 2 · 업종 자동 통과 (Q2=모든 섹터 · 정보성만)."""
    return (True, "all_sectors_pass_through")


async def check_revenue_profit_growth(
    ticker: str,
) -> tuple[bool, bool, list[str]]:
    """단계 3 · 매출 AND 순이익 최근 3년 연속 증가.

    DART FinancialSnapshot · report_code=11011 (사업보고서 · 연간) 최근 3~4년.
    반환: (revenue_growing, net_income_growing, years_used)
    """
    async with get_session() as session:
        stmt = (
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.ticker == ticker,
                FinancialSnapshot.report_code == "11011",
            )
            .order_by(desc(FinancialSnapshot.reference_date))
            .limit(4)
        )
        rows = list((await session.execute(stmt)).scalars().all())

    if len(rows) < 3:
        return (False, False, [])

    # reference_date 내림차순 → 최근 4년 (인덱스 0=가장 최근)
    tail = rows[:4]
    years = [r.reference_date[:4] for r in tail]
    revenues = [r.revenue for r in tail]
    net_incomes = [r.net_income for r in tail]

    def _all_growing(seq: list[Optional[float]]) -> bool:
        # 최근 4개 값 있어야 3개 YoY 계산. 인덱스 3=가장 오래된 → 0=최근
        for a, b in zip(seq[3:0:-1], seq[2::-1]):
            if a is None or b is None or a <= 0:
                return False
            if b <= a:
                return False
        return True

    rev_ok = _all_growing(revenues) if len(revenues) >= 4 else False
    ni_ok = _all_growing(net_incomes) if len(net_incomes) >= 4 else False
    return (rev_ok, ni_ok, list(reversed(years)))


# ─── 단일 종목 스캔 ─────────────────────────────────────────────


async def screen_one(
    ticker: str,
    name: Optional[str],
    market: Optional[str],
    sector: Optional[str],
    market_cap: Optional[float],
    close_price: Optional[float],
) -> BlueChipCandidate:
    """5단계 판정 후 BlueChipCandidate 인스턴스 반환 (session.add 는 상위에서)."""
    # 단계 1
    cap_ok, tier = check_market_cap(market_cap)

    # 단계 2 (자동 통과)
    sector_ok, _sector_note = check_sector_pass_through()

    # 단계 3
    rev_ok, ni_ok, years = await check_revenue_profit_growth(ticker)
    fin_ok = rev_ok and ni_ok

    # 단계 4
    try:
        annual_ok, yoy = await three_year_yoy(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BlueChip · 연봉 조회 실패 · ticker=%s · %s", ticker, exc)
        annual_ok, yoy = False, []

    # 단계 5
    try:
        ma5_ok, months_above = await ma5_persistence(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BlueChip · 월봉 조회 실패 · ticker=%s · %s", ticker, exc)
        ma5_ok, months_above = False, 0

    conditions = {
        "1_market_cap": cap_ok,
        "2_sector": sector_ok,
        "3_financial_growth": fin_ok,
        "4_annual_turnaround": annual_ok,
        "5_monthly_ma5": ma5_ok,
    }
    pass_count = sum(1 for v in conditions.values() if v)
    overall_pass = all(conditions.values())

    reject: list[str] = []
    if not cap_ok:
        reject.append("시총 5조 미달")
    if not fin_ok:
        reject.append("매출·순이익 3년 연속 증가 미달")
    if not annual_ok:
        reject.append("연봉 3년 연평균 증가 미달 (턴어라운드 X)")
    if not ma5_ok:
        reject.append(f"월봉 5MA 위 3개월+ 미달 (연속 {months_above}개월)")

    return BlueChipCandidate(
        run_id="",  # 상위에서 세팅
        ticker=ticker,
        name=name,
        sector=sector,
        market=market,
        market_cap_krw=market_cap,
        tier=tier,
        close_price=close_price,
        revenue_3y_growing=rev_ok,
        net_income_3y_growing=ni_ok,
        financial_years=",".join(years) if years else None,
        annual_turnaround=annual_ok,
        annual_yoy_pcts=",".join(f"{y:.4f}" for y in yoy) if yoy else None,
        monthly_ma5_above=ma5_ok,
        monthly_ma5_months_above=months_above,
        conditions_json=json.dumps(conditions),
        pass_count=pass_count,
        overall_pass=overall_pass,
        reject_reasons=" · ".join(reject) if reject else None,
    )


# ─── 유니버스 조회 ──────────────────────────────────────────────


async def load_universe(min_market_cap: float = TIER_ENTRY_KRW) -> list[dict]:
    """최근 KrxMarketSnapshot 에서 시총 min 이상 종목 · 배치 스캔 대상."""
    async with get_session() as session:
        # 최신 snapshot_date 찾기
        latest = (
            await session.execute(
                select(KrxMarketSnapshot.snapshot_date)
                .order_by(desc(KrxMarketSnapshot.snapshot_date))
                .limit(1)
            )
        ).scalar_one_or_none()
        if not latest:
            return []
        rows = (
            await session.execute(
                select(KrxMarketSnapshot)
                .where(
                    KrxMarketSnapshot.snapshot_date == latest,
                    KrxMarketSnapshot.market_cap.is_not(None),
                    KrxMarketSnapshot.market_cap >= min_market_cap,
                )
                .order_by(desc(KrxMarketSnapshot.market_cap))
            )
        ).scalars().all()
    return [
        {
            "ticker": r.ticker,
            "name": r.name,
            "market": r.market,
            "market_cap": r.market_cap,
            "close_price": r.close_price,
        }
        for r in rows
    ]


# ─── 스크리너 실행 ──────────────────────────────────────────────


async def run_blue_chip_screener(
    trigger: str = "manual",
    limit: Optional[int] = None,
) -> dict:
    """5단계 스크리너 실행 · run_id 생성 · 결과 upsert.

    반환: {"run_id", "universe_size", "passed", "partial", "elapsed_sec"}
    """
    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%SK")
    started = datetime.utcnow()
    git_sha = (os.getenv("GIT_SHA") or "")[:40] or None

    universe = await load_universe()
    if limit:
        universe = universe[:limit]

    # 배치 처리 (동시성 제한)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _scan(row: dict) -> BlueChipCandidate:
        async with sem:
            cand = await screen_one(
                ticker=row["ticker"],
                name=row["name"],
                market=row["market"],
                sector=None,  # v2 · get_market_ticker_and_business_type 추후
                market_cap=row["market_cap"],
                close_price=row["close_price"],
            )
            cand.run_id = run_id
            return cand

    results = await asyncio.gather(*[_scan(r) for r in universe], return_exceptions=True)
    candidates = [c for c in results if isinstance(c, BlueChipCandidate)]

    async with get_session() as session:
        for c in candidates:
            session.add(c)
        session.add(BlueChipRun(
            run_id=run_id,
            ended_at=datetime.utcnow(),
            trigger=trigger,
            universe_size=len(universe),
            passed_count=sum(1 for c in candidates if c.overall_pass),
            partial_count=sum(1 for c in candidates if c.pass_count >= 3 and not c.overall_pass),
            git_sha=git_sha,
        ))
        # started_at 은 server_default. Insert 후 update 대신 명시 값을 세팅하려면 위에서 넘기면 됨.
        await session.commit()

    elapsed = (datetime.utcnow() - started).total_seconds()
    return {
        "run_id": run_id,
        "universe_size": len(universe),
        "passed": sum(1 for c in candidates if c.overall_pass),
        "partial": sum(1 for c in candidates if c.pass_count >= 3 and not c.overall_pass),
        "elapsed_sec": elapsed,
    }
