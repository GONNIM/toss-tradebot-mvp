#!/usr/bin/env python3
"""DART 원본 대조 · verified 5종목 q_yoy 검산.

당기 (latest_yq) · 전년 동기 누적 net_income_owner 를 DART 원본과 대조.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 검증 대상 · (ticker, corp_code, name, latest_year, latest_quarter, expected_current, expected_prev)
# latest_yq 는 API q_yoy 계산 시점의 년/분기
TARGETS = [
    ("006400", "삼성SDI",       2026, 2),   # SURGE
    ("000150", "두산",         2026, 2),   # SURGE
    ("010950", "S-Oil",       2026, 2),   # SURGE
    ("003490", "대한항공",       2026, 2),   # DECLINE
    ("180640", "한진칼",         2026, 2),   # DECLINE
]

# reprt_code 매핑 (1=Q1, 2=반기, 3=Q3, 4=사업보고서)
REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}


async def verify() -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.discovery.data_sources.dart.client import fetch_financial_statement
    from backend.powderkeg.collectors.corp_codes import resolve_corp_code

    print(f"{'TICKER':<8} {'NAME':<10} {'YEAR·Q':>8} {'DART_당기':>15} {'DART_전년동기':>15}")
    print("-" * 65)
    for ticker, name, year, q in TARGETS:
        cc = await resolve_corp_code(ticker)
        if not cc:
            print(f"{ticker} {name} corp_code None")
            continue

        # 당기 · 예: 2026 Q2 반기 (11012)
        curr_items = await fetch_financial_statement(cc, year, REPRT[q])
        curr_v = _extract_owner(curr_items)
        # 전년 동기 · 2025 Q2 반기
        prev_items = await fetch_financial_statement(cc, year - 1, REPRT[q])
        prev_v = _extract_owner(prev_items)

        print(
            f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
            f"{_fmt(curr_v):>15} {_fmt(prev_v):>15}"
        )
    return 0


def _extract_owner(items) -> float | None:
    for it in items:
        aid = it.account_id or ""
        nm = it.account_nm or ""
        if aid == "ifrs-full_ProfitLossAttributableToOwnersOfParent":
            return it.thstrm_amount
        if any(kw in nm for kw in ("지배기업 소유주", "지배회사지분", "지배기업의 소유주")):
            return it.thstrm_amount
    return None


def _fmt(v) -> str:
    if v is None:
        return "None"
    return f"{v/1e12:+.2f}조" if abs(v) >= 1e12 else f"{v/1e8:+.1f}억"


if __name__ == "__main__":
    sys.exit(asyncio.run(verify()))
