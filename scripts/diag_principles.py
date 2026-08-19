#!/usr/bin/env python3
"""Principles 3중 이슈 통합 진단 (2026-08-19).

이슈 A: market_cap 배수 (종목별 다름 · 로직 오류 우선 조사)
이슈 B: FDR industry 컬럼 실 값 (sector detection · KRX 코드 존재 여부)
이슈 C: 삼전 cache 의 dividend_total · buyback_cashflow 실 저장 값
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def diag() -> int:
    import FinanceDataReader as fdr
    from sqlalchemy import select

    from backend.principles.financials import cumulative_to_quarter, ttm_sum
    from backend.services.db import get_session
    from backend.services.models import PrinciplesFinancialCache, PrinciplesResult

    # 대상 · 대형주·금융업·중견주 혼합 10종목
    TICKERS = [
        "005930",  # 삼성전자 (대형)
        "005935",  # 삼성전자우 (우선주 · 중복 합산 검증)
        "000660",  # SK하이닉스
        "105560",  # KB금융 (금융업)
        "055550",  # 신한지주 (금융업)
        "032830",  # 삼성생명 (보험)
        "006400",  # 삼성SDI
        "000270",  # 기아
        "051910",  # LG화학
        "017670",  # SK텔레콤
    ]

    # ─── 이슈 B · FDR 컬럼 확인 ─────
    print("═══ 이슈 B · FDR StockListing 컬럼 · 산업분류 확인 ═══")
    df = await asyncio.to_thread(fdr.StockListing, "KOSPI")
    print(f"total rows: {len(df)}")
    print(f"columns: {list(df.columns)}")
    print()
    print("삼성전자 (005930) row 상세:")
    row = df[df["Code"] == "005930"]
    if len(row) > 0:
        for col, val in row.iloc[0].items():
            print(f"  {col!r:30s} = {val!r}")
    print()
    print("KB금융 (105560) row 상세:")
    row = df[df["Code"] == "105560"]
    if len(row) > 0:
        for col, val in row.iloc[0].items():
            print(f"  {col!r:30s} = {val!r}")

    # ─── 이슈 A · market_cap 배수 표 ─────
    print("\n═══ 이슈 A · market_cap 배수 표 (API 사용 시총 ÷ FDR marcap) ═══")
    async with get_session() as session:
        # 최신 run 결과
        latest = (
            await session.execute(
                select(PrinciplesResult)
                .where(PrinciplesResult.ticker.in_(TICKERS))
                .order_by(PrinciplesResult.run_id.desc())
            )
        ).scalars().all()
        # 최신 run_id 만
        max_run = max((r.run_id for r in latest), default=None)
        latest_by_ticker = {r.ticker: r for r in latest if r.run_id == max_run}

        # 각 종목 cache 로 TTM 계산
        print(f"{'TICKER':>8} {'NAME':>10} {'FDR_MARCAP':>15} {'TTM_NI':>12} "
              f"{'API_PER':>10} {'API_MARCAP':>15} {'RATIO':>8}")
        for ticker in TICKERS:
            fdr_row = df[df["Code"] == ticker]
            fdr_mc = float(fdr_row.iloc[0]["Marcap"]) if len(fdr_row) else None
            fdr_name = fdr_row.iloc[0]["Name"] if len(fdr_row) else "?"

            # cache 로 TTM 계산
            cache_rows = (
                await session.execute(
                    select(PrinciplesFinancialCache).where(
                        PrinciplesFinancialCache.ticker == ticker
                    )
                )
            ).scalars().all()
            by_yq = {(r.fiscal_year, r.fiscal_quarter): r for r in cache_rows}
            years_desc = sorted({y for y, q in by_yq if q == 4}, reverse=True)
            ttm_ni = None
            if years_desc:
                series = []
                for y in reversed(years_desc[:2]):
                    cum = {
                        q: getattr(by_yq[(y, q)], "net_income_owner_cum", None)
                        if (y, q) in by_yq else None
                        for q in (1, 2, 3, 4)
                    }
                    q_flow = cumulative_to_quarter(cum)
                    for q in (1, 2, 3, 4):
                        series.append(q_flow[q])
                ttm_ni = ttm_sum(series)

            api_result = latest_by_ticker.get(ticker)
            api_per = api_result.per_ttm if api_result else None
            api_mc = None
            ratio = None
            if api_per and ttm_ni:
                api_mc = api_per * ttm_ni  # per_ttm × 순이익 = 사용 시총
                if fdr_mc:
                    ratio = api_mc / fdr_mc

            print(
                f"{ticker:>8} {fdr_name[:8]:>10} "
                f"{_fmt(fdr_mc):>15} {_fmt(ttm_ni):>12} "
                f"{api_per or 0:>10.2f} {_fmt(api_mc):>15} "
                f"{ratio or 0:>8.2f}"
            )

    # ─── 이슈 C · 삼전 dividend_total · buyback_cashflow ─────
    print("\n═══ 이슈 C · 삼전 · SK하이닉스 · KB금융 cache 배당/자기주식 저장 값 ═══")
    async with get_session() as session:
        for ticker in ["005930", "000660", "105560"]:
            rows = (
                await session.execute(
                    select(PrinciplesFinancialCache).where(
                        PrinciplesFinancialCache.ticker == ticker,
                        PrinciplesFinancialCache.fiscal_quarter == 4,
                    )
                    .order_by(PrinciplesFinancialCache.fiscal_year.desc())
                )
            ).scalars().all()
            print(f"\n── {ticker} · Q4 사업보고서 rows ──")
            print(f"{'YEAR':>6} {'DPS':>8} {'DIV_TOTAL':>15} {'BUYBACK':>15}")
            for r in rows:
                print(
                    f"{r.fiscal_year:>6} {_fmt(r.dividend_per_share):>8} "
                    f"{_fmt(r.dividend_total):>15} {_fmt(r.buyback_cashflow_cum):>15}"
                )
    return 0


def _fmt(v):
    if v is None:
        return "None"
    try:
        if abs(v) >= 1e12:
            return f"{v / 1e12:.2f}조"
        if abs(v) >= 1e8:
            return f"{v / 1e8:.2f}억"
        if abs(v) >= 1e4:
            return f"{v / 1e4:.1f}만"
        return f"{v:.1f}"
    except TypeError:
        return str(v)


if __name__ == "__main__":
    sys.exit(asyncio.run(diag()))
