#!/usr/bin/env python3
"""Principles 캐시 진단 · 특정 티커의 분기별 원본값 출력.

용법:
    python scripts/inspect_principles_cache.py 005930
    python scripts/inspect_principles_cache.py 005930 000660
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def inspect(tickers: list[str]) -> int:
    from sqlalchemy import select

    from backend.principles.financials import cumulative_to_quarter, ttm_sum
    from backend.services.db import get_session
    from backend.services.models import PrinciplesFinancialCache

    async with get_session() as session:
        for ticker in tickers:
            rows = (
                await session.execute(
                    select(PrinciplesFinancialCache)
                    .where(PrinciplesFinancialCache.ticker == ticker)
                    .order_by(
                        PrinciplesFinancialCache.fiscal_year.desc(),
                        PrinciplesFinancialCache.fiscal_quarter.desc(),
                    )
                )
            ).scalars().all()
            print(f"\n═══ {ticker} · {len(rows)} rows ═══")
            print(
                f"{'YEAR':>6} {'Q':>3} {'REPRT':>6}  "
                f"{'NI_OWNER':>18} {'NI':>18} {'OP':>18} {'REV':>18} "
                f"{'INTEREST':>14}  {'DPS':>8}"
            )
            by_yq: dict[tuple[int, int], PrinciplesFinancialCache] = {}
            for r in rows:
                by_yq[(r.fiscal_year, r.fiscal_quarter)] = r
                reprt = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}[r.fiscal_quarter]
                q_meaning = {1: "3M", 2: "6M(H)", 3: "9M(Q3)", 4: "12M(FY)"}[r.fiscal_quarter]
                print(
                    f"{r.fiscal_year:>6} {r.fiscal_quarter:>3} {reprt}({q_meaning[:5]:>5})  "
                    f"{_fmt(r.net_income_owner_cum):>18} "
                    f"{'-':>18} "
                    f"{_fmt(r.operating_income_cum):>18} "
                    f"{_fmt(r.revenue_cum):>18} "
                    f"{_fmt(r.interest_expense_cum):>14}  "
                    f"{_fmt(r.dividend_per_share):>8}"
                )

            # 최근 2년 TTM 분해
            years_desc = sorted({y for y, q in by_yq if q == 4}, reverse=True)
            if len(years_desc) >= 1:
                print("\n── TTM 분해 (net_income_owner) ──")
                for attr, label in [
                    ("net_income_owner_cum", "지배주주순이익"),
                    ("operating_income_cum", "영업이익"),
                    ("revenue_cum", "매출"),
                ]:
                    series: list = []
                    for y in reversed(years_desc[:2]):  # 오래된 → 최근
                        cum = {
                            q: getattr(by_yq[(y, q)], attr) if (y, q) in by_yq else None
                            for q in (1, 2, 3, 4)
                        }
                        q_flow = cumulative_to_quarter(cum)
                        for q in (1, 2, 3, 4):
                            series.append((y, q, cum[q], q_flow[q]))
                    print(f"\n  [{label}]")
                    print(f"  {'YEAR':>6} {'Q':>3} {'CUM':>18} {'STANDALONE':>18}")
                    for y, q, cum, standalone in series:
                        print(
                            f"  {y:>6} {q:>3} {_fmt(cum):>18} {_fmt(standalone):>18}"
                        )
                    standalones = [s for _, _, _, s in series]
                    naive_sum_of_4_cum = sum(
                        c for _, _, c, _ in series[-4:] if c is not None
                    )
                    ttm = ttm_sum(standalones)
                    print(f"  → naive_sum_of_4_cum (WRONG): {_fmt(naive_sum_of_4_cum)}")
                    print(f"  → TTM (proper Q단독 sum) : {_fmt(ttm)}")
                    if years_desc:
                        y_latest = years_desc[0]
                        r_latest_fy = by_yq.get((y_latest, 4))
                        annual = getattr(r_latest_fy, attr, None) if r_latest_fy else None
                        print(f"  → 최근 사업보고서 연간   : {_fmt(annual)}")

    return 0


def _fmt(v) -> str:
    if v is None:
        return "None"
    if abs(v) >= 1e12:
        return f"{v / 1e12:.2f}조"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}억"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.1f}만"
    return f"{v:.1f}"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/inspect_principles_cache.py <ticker> [ticker ...]")
        return 1
    return asyncio.run(inspect(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
