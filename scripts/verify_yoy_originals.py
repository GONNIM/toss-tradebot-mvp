#!/usr/bin/env python3
"""공시 원문 대조 · 캐시 검증 (파서 복제 아님).

사고 회고 (2026-08-21) · 파서와 verify 가 동일 API 를 사용해 서로 채점하면
"자기 채점" 이 되어 검증력이 없음. 이 스크립트는 공시 원문 값 (DART 뷰어
연결재무제표 페이지에서 사람이 읽은 숫자) 을 JSON 으로 수동 입력받아
principles_financial_cache 와 대조함.

용법
----
    # 준비된 원문 JSON 파일로 대조
    python scripts/verify_yoy_originals.py --file scripts/dart_originals.json

    # stdin 으로 입력 (heredoc)
    python scripts/verify_yoy_originals.py --file - <<'EOF'
    [
      {
        "ticker": "006400", "name": "삼성SDI", "year": 2026, "quarter": 2,
        "owner_ni_krw": 342190000000,
        "doc": "삼성SDI 2026 반기보고서 · 연결 CIS · 지배기업지분"
      }
    ]
    EOF

원문 JSON 스키마 (per 종목)
- ticker (str, 6자리)
- name (str)
- year (int)
- quarter (int · 1=Q1 · 2=반기 · 3=Q3 · 4=사업보고서)
- owner_ni_krw (float · 지배주주 반기순이익 · KRW · DART 뷰어 원문)
- doc (str · 문서명·페이지·항목명 그대로)

대조 규칙
- 원문값 vs cache.net_income_owner
- 1% 오차 이내 → OK · 그 외 diff 표시
- cache row 없거나 net_income_owner=None → MISSING
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


TOL_RATIO = 0.01  # 1% 허용


async def verify(entries: list[dict]) -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.services.db import get_session
    from backend.services.models import PrinciplesFinancialCache

    ok = 0
    mismatch = 0
    missing = 0
    print(
        f"{'TICKER':<8} {'NAME':<10} {'YEAR·Q':>8} "
        f"{'ORIGINAL':>15} {'CACHE':>15} {'MATCH':>6}  {'DOC'}"
    )
    print("-" * 110)
    async with get_session() as session:
        for e in entries:
            ticker = e["ticker"]
            name = e.get("name", "")
            year = int(e["year"])
            q = int(e["quarter"])
            original = float(e["owner_ni_krw"])
            doc = e.get("doc", "")

            row = (await session.execute(
                select(PrinciplesFinancialCache)
                .where(PrinciplesFinancialCache.ticker == ticker)
                .where(PrinciplesFinancialCache.fiscal_year == year)
                .where(PrinciplesFinancialCache.fiscal_quarter == q)
            )).scalar_one_or_none()
            if row is None:
                print(
                    f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                    f"{_fmt(original):>15} {'MISSING':>15} {'❓':>6}  {doc[:50]}"
                )
                missing += 1
                continue
            cache_v = row.net_income_owner
            if cache_v is None:
                print(
                    f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                    f"{_fmt(original):>15} {'None':>15} {'❓':>6}  {doc[:50]}"
                )
                missing += 1
                continue
            tol = abs(original) * TOL_RATIO
            match = abs(cache_v - original) <= tol
            if match:
                ok += 1
            else:
                mismatch += 1
            print(
                f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                f"{_fmt(original):>15} {_fmt(cache_v):>15} "
                f"{'✅' if match else '❌':>6}  {doc[:50]}"
            )

    print()
    print(f"OK={ok} · MISMATCH={mismatch} · MISSING={missing}")
    return 0 if (mismatch == 0 and missing == 0) else 1


def _fmt(v) -> str:
    if v is None:
        return "None"
    return f"{v/1e12:+.3f}조" if abs(v) >= 1e12 else f"{v/1e8:+.1f}억"


def _load(path: str) -> list[dict]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="공시 원문 대조 · 캐시 검증 (파서 복제 아님)"
    )
    parser.add_argument(
        "--file", "-f",
        default="scripts/dart_originals.json",
        help="원문 JSON 경로 · '-' 는 stdin",
    )
    args = parser.parse_args()
    entries = _load(args.file)
    if not isinstance(entries, list):
        print("JSON 은 list of dict 이어야 함", file=sys.stderr)
        return 2
    return asyncio.run(verify(entries))


if __name__ == "__main__":
    sys.exit(main())
