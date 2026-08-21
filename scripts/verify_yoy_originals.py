#!/usr/bin/env python3
"""공시 원문 대조 · 캐시 검증 (파서 복제 아님).

사고 회고 (2026-08-21) · 파서와 verify 가 동일 API 를 사용해 서로 채점하면
"자기 채점" 이 되어 검증력이 없음. 이 스크립트는 공시 원문 값 (DART 뷰어
연결재무제표 페이지에서 사람이 읽은 숫자) 을 JSON 으로 수동 입력받아
principles_financial_cache 와 대조함.

용법
----
    python scripts/verify_yoy_originals.py --file scripts/dart_originals.json

JSON 스키마 (파일 레벨 unit 고정 · 종목별 상이 단위 금지)
    {
      "unit": "million_krw",
      "note": "설명",
      "entries": [
        {
          "ticker": "006400",
          "name": "삼성SDI",
          "year": 2026,
          "quarter": 2,
          "owner_ni": 342190,
          "doc": "삼성SDI 2026 반기보고서 · 연결 CIS · 지배기업지분 (백만원)"
        },
        ...
      ]
    }

- ticker (str, 6자리)
- year (int) · quarter (int · 1=Q1, 2=반기, 3=Q3, 4=사업보고서)
- owner_ni (number · 지배주주 반기순이익 · 파일 unit 단위 · 손실은 -X)
- doc (str · 문서명·페이지·항목명 그대로)

단위 처리
- 파일 unit="million_krw" → owner_ni × 1,000,000 후 원 단위 캐시와 대조
- unit 누락 or 미지원 → 실행 거부 (조용한 미환산 방지)

허용 오차
- ±0.1% 이내 일치 → OK (반올림·표기 자릿수 감안)
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


TOL_RATIO = 0.001  # 0.1% 허용 (반올림·표기 자릿수 차이)

_UNITS: dict[str, int] = {
    "million_krw": 1_000_000,
}


async def verify(entries: list[dict], multiplier: int, unit_label: str) -> int:
    from backend.services import config  # noqa: F401
    from sqlalchemy import select

    from backend.services.db import get_session
    from backend.services.models import PrinciplesFinancialCache

    ok = 0
    mismatch = 0
    missing = 0
    print(f"UNIT = {unit_label} (multiplier ×{multiplier:,})")
    print(f"TOL  = ±{TOL_RATIO * 100:.2f}%")
    print()
    print(
        f"{'TICKER':<8} {'NAME':<10} {'YEAR·Q':>7} "
        f"{'ORIGINAL (KRW · 조)':>36} {'CACHE (KRW · 조)':>36} "
        f"{'MATCH':>6}  DOC"
    )
    print("-" * 140)
    async with get_session() as session:
        for e in entries:
            ticker = e["ticker"]
            name = e.get("name", "")
            year = int(e["year"])
            q = int(e["quarter"])
            raw_val = e.get("owner_ni")
            doc = e.get("doc", "")

            if raw_val is None:
                print(
                    f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                    f"{'(NULL · 원문 미입력)':>36} {'-':>36} {'❓':>6}  {doc[:60]}"
                )
                missing += 1
                continue

            original = float(raw_val) * multiplier  # 원 단위 환산

            row = (await session.execute(
                select(PrinciplesFinancialCache)
                .where(PrinciplesFinancialCache.ticker == ticker)
                .where(PrinciplesFinancialCache.fiscal_year == year)
                .where(PrinciplesFinancialCache.fiscal_quarter == q)
            )).scalar_one_or_none()
            if row is None:
                print(
                    f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                    f"{_fmt_pair(original):>36} {'CACHE ROW MISSING':>36} {'❓':>6}  {doc[:60]}"
                )
                missing += 1
                continue
            cache_v = row.net_income_owner
            if cache_v is None:
                print(
                    f"{ticker:<8} {name[:8]:<10} {year}Q{q:>2}   "
                    f"{_fmt_pair(original):>36} {'net_income_owner=None':>36} {'❓':>6}  {doc[:60]}"
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
                f"{_fmt_pair(original):>36} {_fmt_pair(cache_v):>36} "
                f"{'✅' if match else '❌':>6}  {doc[:60]}"
            )

    print()
    print(f"OK={ok} · MISMATCH={mismatch} · MISSING={missing}")
    return 0 if (mismatch == 0 and missing == 0) else 1


def _fmt_pair(v: float | None) -> str:
    """`+342,190,000,000원 (+0.342조)` 형태로 원 단위·조 단위 병기."""
    if v is None:
        return "None"
    kor = f"{v / 1e12:+.3f}조" if abs(v) >= 1e12 else f"{v / 1e8:+.1f}억"
    return f"{v:+,.0f}원 ({kor})"


def _load(path: str) -> tuple[dict, list[dict]]:
    if path == "-":
        raw = json.load(sys.stdin)
    else:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(
            "JSON 최상위는 {unit, entries[]} 스키마여야 함 · list 는 구버전"
        )
    if "unit" not in raw or "entries" not in raw:
        raise SystemExit(
            "필수 필드 누락 · JSON 최상위에 'unit' 과 'entries' 둘 다 필요"
        )
    if not isinstance(raw["entries"], list):
        raise SystemExit("'entries' 는 list 여야 함")
    return raw, raw["entries"]


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
    header, entries = _load(args.file)
    unit = header.get("unit")
    if unit not in _UNITS:
        print(
            f"unit 필수 · 지원 값: {sorted(_UNITS)} · 실제: {unit!r} "
            f"→ 실행 거부 (조용한 미환산 방지)",
            file=sys.stderr,
        )
        return 2
    multiplier = _UNITS[unit]
    return asyncio.run(verify(entries, multiplier, unit))


if __name__ == "__main__":
    sys.exit(main())
