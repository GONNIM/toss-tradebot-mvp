#!/usr/bin/env python3
"""두산 2026 Q2 · net_income_owner 후보 행 전체 dump.

parse_principles_financials 가 어떤 계정을 잡는지 · verify 가 잡는 값이 어디서
왔는지 확진.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


TARGETS = [("000150", "두산", 2026, "11012"), ("010950", "S-Oil", 2026, "11012")]


async def dump() -> int:
    from backend.services import config  # noqa: F401

    from backend.discovery.data_sources.dart.client import fetch_financial_statement
    from backend.powderkeg.collectors.corp_codes import resolve_corp_code

    for ticker, name, year, reprt in TARGETS:
        cc = await resolve_corp_code(ticker)
        items = await fetch_financial_statement(cc, year, reprt)
        print(f"\n═══ {ticker} {name} · {year} {reprt} · total {len(items)} items ═══")
        # 지배주주 · 순이익 · profit 관련 모든 행 필터
        cnt = 0
        for it in items:
            aid = (it.account_id or "").lower()
            nm = it.account_nm or ""
            v = it.thstrm_amount
            sj = it.sj_div or ""
            fs = it.fs_nm or ""
            keywords = ("owner", "profitloss", "지배", "당기순이익", "순이익")
            if any(kw in aid for kw in ("owner", "profitloss")) or any(kw in nm for kw in ("지배", "당기순이익", "순이익")):
                cnt += 1
                v_str = f"{v/1e12:+.3f}조" if v and abs(v) >= 1e12 else (f"{v/1e8:+.1f}억" if v else "None")
                print(f"  [{sj:>4}] fs={fs[:10]:<10} nm={nm[:35]:<35} id={aid[:60]:<60} val={v_str}")
        print(f"  → {cnt}건 매치")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(dump()))
