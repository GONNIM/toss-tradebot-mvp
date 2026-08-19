#!/usr/bin/env python3
"""DART 원본 검증 · 삼전 2026 Q1/반기 지배기업 소유주지분 순이익.

캐시 값과 DART API 원본 응답 대조 · PER 13.15 공식 채택 판정용.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def verify() -> int:
    # config import → backend/.env 자동 로드 (DART_API_KEY 포함)
    from backend.services import config  # noqa: F401
    from backend.discovery.data_sources.dart.client import fetch_financial_statement

    CORP = "00126380"  # 삼성전자
    print(f"═══ DART 원본 검증 · 삼전 (corp={CORP}) ═══\n")

    for label, year, reprt in [
        ("2026 Q1 (1분기보고서)", 2026, "11013"),
        ("2026 반기 (반기보고서)", 2026, "11012"),
        ("2025 사업보고서 (연간)", 2025, "11011"),
    ]:
        print(f"── {label} · bsns_year={year} · reprt={reprt} ──")
        items = await fetch_financial_statement(CORP, year, reprt, fs_div="CFS")
        if not items:
            print("  응답 empty\n")
            continue
        # net_income_owner (지배주주) 관련 계정 필터
        for it in items:
            nm = it.account_nm or ""
            aid = it.account_id or ""
            if (
                "지배" in nm and "당기순이익" in nm
            ) or aid == "ifrs-full_ProfitLossAttributableToOwnersOfParent":
                # 지배기업 소유주 귀속 당기순이익
                v = it.thstrm_amount
                v_str = f"{v/1e12:.2f}조" if v else "None"
                print(f"  [지배주주] account_id={aid!r}")
                print(f"           account_nm={nm!r}")
                print(f"           thstrm_amount={v_str} (원)")
                break
        # 일반 당기순이익도 참조
        for it in items:
            if it.account_id == "ifrs-full_ProfitLoss":
                v = it.thstrm_amount
                v_str = f"{v/1e12:.2f}조" if v else "None"
                print(f"  [총순이익 참조] {v_str}")
                break
        print()

    print("═══ 캐시 값 대조 ═══")
    print("  Q1'26 캐시: 47.10조 · 반기'26 캐시: 71.27조 · 2025 연간: 44.26조")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(verify()))
