"""Serenity per-ticker seed · Phase L4 · 2026-08-02.

theses.md · methodology.md · track-record.md 정독 결과 사용자 수동 편집.
문서 03-implementation-plan.md §L4 예시를 SSOT 로 관리 · 추후 확장.

주의:
    - financing_tier / serenity_tier / anti_pattern_flags / domain_tags 는 자동 추출 어려움
      → 여기서 seed · 이후 refresh_all_scores 가 aggregate 합쳐 total_score/auto_avoid 재계산
    - bottleneck_score, mag7_customer_count 등도 수동 (문서 §L 관찰 로그 참조)
    - anti_pattern_flags 는 list · scorer._csv_from_list 로 자동 CSV 저장
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.discovery.serenity.scorer import refresh_all_scores, upsert_seed

logger = logging.getLogger(__name__)


# 문서 §L4 예시 · 관찰 로그 §L·§K 근거
SEED: list[dict[str, Any]] = [
    {
        "ticker": "NBIS", "financing_tier": "S", "serenity_tier": "S",
        "domain_tags": ["neocloud"], "anti_pattern_flags": [],
        "bottleneck_score": 8, "mag7_customer_count": 5,
        "contracted_arr_multiple": 4.0, "is_pre_ramp": False,
        "active_atm_pct_of_mc": 0.0,
    },
    {
        "ticker": "AXTI", "financing_tier": "A", "serenity_tier": "A",
        "domain_tags": ["inp_substrates"], "anti_pattern_flags": [],
        "bottleneck_score": 9, "mag7_customer_count": 3,
        "is_pre_ramp": True, "gaap_gross_margin": 55.0,
        "active_atm_pct_of_mc": 5.0,
    },
    {
        "ticker": "SIVE", "financing_tier": "B", "serenity_tier": "S",
        "domain_tags": ["optical_cpo"], "anti_pattern_flags": [],
        "bottleneck_score": 9, "mag7_customer_count": 4,
        "is_pre_ramp": True, "active_atm_pct_of_mc": 10.0,
    },
    {
        "ticker": "LITE", "financing_tier": "B", "serenity_tier": "B",
        "domain_tags": ["optical_cpo"], "anti_pattern_flags": [],
        "bottleneck_score": 7, "mag7_customer_count": 4,
        "gaap_gross_margin": 45.0, "active_atm_pct_of_mc": 0.0,
    },
    {
        "ticker": "AAOI", "financing_tier": "C", "serenity_tier": "B",
        "domain_tags": ["optical_cpo"],
        "anti_pattern_flags": ["no_cpo_design_win"],
        "bottleneck_score": 5, "mag7_customer_count": 2,
        "active_atm_pct_of_mc": 20.0,
    },
    {
        "ticker": "IREN", "financing_tier": "D", "serenity_tier": "F",
        "domain_tags": ["neocloud"],
        "anti_pattern_flags": ["atm_51pct_overhang", "sbc_1p14b"],
        "bottleneck_score": 3, "mag7_customer_count": 1,
        "active_atm_pct_of_mc": 51.0,
    },
    {
        "ticker": "CRWV", "financing_tier": "F", "serenity_tier": "F",
        "domain_tags": ["neocloud"],
        "anti_pattern_flags": ["heavy_debt_1p3b_yr"],
        "bottleneck_score": 2, "mag7_customer_count": 2,
        "active_atm_pct_of_mc": 8.0,
    },
]


async def apply_seed(seed: list[dict[str, Any]] | None = None) -> dict:
    """SEED 리스트 upsert + 스코어 즉시 재계산.

    반환: {"upserted": N, "score_refresh": {...}}
    """
    seed = seed or SEED
    for row in seed:
        await upsert_seed(row)
    score_result = await refresh_all_scores()
    return {"upserted": len(seed), "score_refresh": score_result}


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Serenity per-ticker seed 적용")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    )
    result = asyncio.run(apply_seed())
    print(f"Serenity seed 완료: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
