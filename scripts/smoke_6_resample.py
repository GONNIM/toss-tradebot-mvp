#!/usr/bin/env python3
"""v1.0.7 스모크 · 파서 계약 fix 후 6종목 재수집 + verify 6/6 + 삼전 TTM 등가.

사용자 지시 (2026-08-21):
  전체 재수집 진행 조건 = 이 스모크 통과. 6/6 미달 시 전체 재수집 금지 · 진단 보고.

절차:
  1) 6종목 (005930·006400·000150·010950·003490·180640) · 2026 Q2 반기보고서 fetch
     + 파서 v1.0.7 (add 우선 · fallback 플래그) 로 재수집 → 캐시 upsert
  2) verify_yoy_originals 스타일 대조 (dart_originals.json 원문 값 vs 캐시 값)
  3) 삼전 TTM 재계산 · 110.60조 등가 확인 (누적 저장 + _standalone_series 분해)

승인 범위:
  - DART API 호출 6종목 × 1분기 = 6회 (rate limit 부담 없음 · 200ms sleep)
  - 로컬 실행 시 로컬 sqlite 필요 · 서버 실행 권장 (screener 캐시가 서버)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


DART_SLEEP = 0.2

# 6종목 · (ticker, name)
TARGETS: list[tuple[str, str]] = [
    ("005930", "삼성전자"),
    ("006400", "삼성SDI"),
    ("000150", "두산"),
    ("010950", "S-Oil"),
    ("003490", "대한항공"),
    ("180640", "한진칼"),
]

YEAR = 2026
QUARTER = 2
REPRT = "11012"  # 반기


async def _resample_one(session, ticker: str, corp_code: str):
    from backend.discovery.data_sources.dart.client import fetch_financial_statement
    from backend.principles.financials import parse_principles_financials
    from backend.services.models import PrinciplesFinancialCache
    from sqlalchemy import select

    items = await fetch_financial_statement(corp_code, YEAR, REPRT)
    await asyncio.sleep(DART_SLEEP)
    parsed = parse_principles_financials(items, reprt_code=REPRT)
    cum_fallback = None
    if parsed.fallback_fields:
        cum_fallback = json.dumps(sorted(parsed.fallback_fields))

    row = (await session.execute(
        select(PrinciplesFinancialCache)
        .where(PrinciplesFinancialCache.ticker == ticker)
        .where(PrinciplesFinancialCache.fiscal_year == YEAR)
        .where(PrinciplesFinancialCache.fiscal_quarter == QUARTER)
    )).scalar_one_or_none()
    if row is None:
        session.add(PrinciplesFinancialCache(
            ticker=ticker, fiscal_year=YEAR, fiscal_quarter=QUARTER,
            corp_code=corp_code,
            revenue_cum=parsed.revenue,
            operating_income_cum=parsed.operating_income,
            net_income_owner_cum=parsed.net_income_owner or parsed.net_income,
            interest_expense_cum=parsed.interest_expense,
            total_assets=parsed.total_assets,
            total_liabilities=parsed.total_liabilities,
            total_equity=parsed.total_equity,
            buyback_cashflow_cum=(abs(parsed.buyback_cashflow) if parsed.buyback_cashflow else None),
            cum_fallback_fields=cum_fallback,
        ))
    else:
        row.revenue_cum = parsed.revenue
        row.operating_income_cum = parsed.operating_income
        row.net_income_owner_cum = parsed.net_income_owner or parsed.net_income
        row.interest_expense_cum = parsed.interest_expense
        row.total_assets = parsed.total_assets
        row.total_liabilities = parsed.total_liabilities
        row.total_equity = parsed.total_equity
        row.buyback_cashflow_cum = abs(parsed.buyback_cashflow) if parsed.buyback_cashflow else None
        row.cum_fallback_fields = cum_fallback
    return parsed


async def _verify_vs_originals(session, originals: list[dict]) -> tuple[int, int]:
    """dart_originals.json entries vs 재수집 후 캐시 net_income_owner_cum."""
    from backend.services.models import PrinciplesFinancialCache
    from sqlalchemy import select

    ok = 0
    fail = 0
    tol_ratio = 0.001  # ±0.1%
    print()
    print(f"{'TICKER':<8} {'NAME':<10} {'ORIGINAL (원 · 조)':>36} {'CACHE (원 · 조)':>36} MATCH")
    print("-" * 130)
    for e in originals:
        t = e["ticker"]
        original = float(e["owner_ni"])  # 파일 unit=krw 전제 (dart_originals.json)
        row = (await session.execute(
            select(PrinciplesFinancialCache)
            .where(PrinciplesFinancialCache.ticker == t)
            .where(PrinciplesFinancialCache.fiscal_year == YEAR)
            .where(PrinciplesFinancialCache.fiscal_quarter == QUARTER)
        )).scalar_one_or_none()
        cache = row.net_income_owner_cum if row else None
        match = cache is not None and abs(cache - original) <= abs(original) * tol_ratio
        if match:
            ok += 1
        else:
            fail += 1

        def _fp(v):
            if v is None:
                return "None"
            kor = f"{v / 1e12:+.3f}조" if abs(v) >= 1e12 else f"{v / 1e8:+.1f}억"
            return f"{v:+,.0f}원 ({kor})"

        print(f"{t:<8} {e.get('name', '')[:8]:<10} "
              f"{_fp(original):>36} {_fp(cache):>36} {'OK' if match else 'FAIL'}")
    return ok, fail


async def _samsung_ttm_equiv(session) -> bool:
    """005930 캐시 최근 5개 분기 (2025Q2~2026Q2) 로 TTM 계산 · 110.60조 등가."""
    from backend.principles.financials import ttm_sum
    from backend.services.models import PrinciplesFinancialCache
    from sqlalchemy import select

    rows = (await session.execute(
        select(PrinciplesFinancialCache)
        .where(PrinciplesFinancialCache.ticker == "005930")
        .order_by(PrinciplesFinancialCache.fiscal_year,
                  PrinciplesFinancialCache.fiscal_quarter)
    )).scalars().all()
    by_yq = {(r.fiscal_year, r.fiscal_quarter): r for r in rows}
    all_yq = sorted(by_yq.keys())
    series = []
    for (y, q) in all_yq:
        cum = by_yq[(y, q)].net_income_owner_cum
        if cum is None:
            series.append(None)
            continue
        if q == 1:
            series.append(cum)
        else:
            prev = by_yq.get((y, q - 1))
            prev_cum = prev.net_income_owner_cum if prev else None
            series.append(cum - prev_cum if prev_cum is not None else None)
    ttm = ttm_sum(series)
    print()
    print(f"삼전 TTM (누적 저장 + Q단독 분해 최근 4Q 합) = {ttm/1e12 if ttm else 'None'}조")
    if ttm is None:
        return False
    ok = abs(ttm - 110.60e12) < 0.05e12  # ±0.05조 허용
    print(f"기대값 = 110.60조 · 오차 ≤ 0.05조 · {'OK' if ok else 'FAIL'}")
    return ok


async def smoke() -> int:
    from backend.services import config  # noqa: F401
    from backend.powderkeg.collectors.corp_codes import resolve_many
    from backend.services.db import get_session

    corp_map = await resolve_many([t for t, _ in TARGETS])
    async with get_session() as session:
        for t, name in TARGETS:
            cc = corp_map.get(t)
            if not cc:
                print(f"[skip] {t} {name} corp_code None")
                continue
            parsed = await _resample_one(session, t, cc)
            fbn = sorted(parsed.fallback_fields)
            print(f"[resampled] {t} {name} · ni_owner={parsed.net_income_owner} · fallback={fbn}")
        await session.commit()

        # verify vs 원문
        originals_path = _PROJECT_ROOT / "scripts" / "dart_originals.json"
        raw = json.loads(originals_path.read_text(encoding="utf-8"))
        entries = raw["entries"] if isinstance(raw, dict) else raw
        # 삼전 원문 값 없으면 5종목만 대조 · 6번째 (삼전) 은 TTM 등가로 판정
        ok, fail = await _verify_vs_originals(session, entries)
        print(f"\nOriginal verify · OK={ok} · FAIL={fail} (5종목 기준)")

        # 삼전 TTM 등가 (6번째 판정)
        ttm_ok = await _samsung_ttm_equiv(session)

    total_ok = ok + (1 if ttm_ok else 0)
    total = len(entries) + 1  # 원문 5 + 삼전 TTM 1 = 6
    print(f"\n=== 스모크 최종 · {total_ok}/{total} OK ===")
    return 0 if total_ok == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(smoke()))
