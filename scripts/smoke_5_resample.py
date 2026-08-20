#!/usr/bin/env python3
"""파서 sj_div fix 스모크 · 5종목만 재수집 → DART 원본 값 대조.

용법:
    python scripts/smoke_5_resample.py

- 5종목 (삼성SDI, 두산, S-Oil, 대한항공, 한진칼) 2026 Q2 반기 재fetch
- 파서 새 로직으로 net_income_owner 파싱
- DART 원본 (verify_yoy_originals.py 값) 과 대조
- 5/5 일치 시 exit 0 · 하나라도 불일치 시 exit 1
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# (ticker, name, expected_owner_krw · DART 원본)
EXPECTED = [
    ("006400", "삼성SDI",   342190000000.0),
    ("000150", "두산",      2_614_000_000_000.0),  # +2.61조
    ("010950", "S-Oil",   10_090_000_000_000.0),
    ("003490", "대한항공",   10_510_000_000_000.0),
    ("180640", "한진칼",      3_340_000_000_000.0),
]
YEAR = 2026
REPRT = "11012"  # 반기


async def smoke() -> int:
    from backend.services import config  # noqa: F401

    from backend.discovery.data_sources.dart.client import fetch_financial_statement
    from backend.powderkeg.collectors.corp_codes import resolve_corp_code
    from backend.principles.financials import parse_principles_financials

    print(f"{'TICKER':<8} {'NAME':<10} {'EXPECTED':>15} {'PARSED':>15} {'MATCH':>6}  {'ACCT'}")
    print("-" * 90)
    all_match = True
    for ticker, name, expected in EXPECTED:
        cc = await resolve_corp_code(ticker)
        items = await fetch_financial_statement(cc, YEAR, REPRT)
        parsed = parse_principles_financials(items)
        got = parsed.net_income_owner or parsed.net_income
        matched_acct = parsed.matched.get("net_income_owner") or parsed.matched.get("net_income", "?")
        tol = abs(expected) * 0.01  # 1% 오차 허용
        match = got is not None and abs(got - expected) <= tol
        if not match:
            all_match = False
        print(
            f"{ticker:<8} {name[:8]:<10} {_fmt(expected):>15} {_fmt(got):>15} "
            f"{'✅' if match else '❌':>6}  {matched_acct[:40]}"
        )
    print()
    if all_match:
        print("✅ 5/5 일치 · 파서 fix 정상")
        return 0
    else:
        print("❌ 불일치 종목 있음 · 파서 재조사 필요")
        return 1


def _fmt(v) -> str:
    if v is None:
        return "None"
    return f"{v/1e12:+.3f}조" if abs(v) >= 1e12 else f"{v/1e8:+.1f}억"


if __name__ == "__main__":
    sys.exit(asyncio.run(smoke()))
