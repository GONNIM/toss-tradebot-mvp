"""Market regime 자동 태깅 · Phase B 주 3-3 (stub · 데이터 축적 후 활성).

참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1-1 (market_regime)
      docs/plans/toss-tradebot-tobe/stage1-optimization.md §1-4 (자동 태깅 · KOSPI 20MA·VKOSPI)

현 상태 (2026-07-30):
    KOSPI DailyCandle 축적 부재 · Phase 2 완전 PIT 준비 시 축적 스케줄러 신설 예정.
    지금은 unknown 기본값 · 판정 생성 API 가 override 가능.

Regime 카테고리:
    bull    — KOSPI > 20MA × 1.03 (선명한 상승 추세)
    bear    — KOSPI < 20MA × 0.97 (선명한 하락 추세)
    choppy  — 근처 (±3%) · 방향성 미명확
    crisis  — VKOSPI > 30 (변동성 폭증 · 미구현)
    unknown — 데이터 부족 (default · 축적 부재)
"""

from __future__ import annotations

from typing import Literal

MarketRegime = Literal["bull", "bear", "choppy", "crisis", "unknown"]


async def infer_market_regime() -> MarketRegime:
    """자동 태깅 · 데이터 축적 후 활성화 예정.

    현 반환값: "unknown" (KOSPI DailyCandle 축적 부재)

    미래 로직 (Phase 2 완전 PIT · KOSPI 스케줄러 후):
        1. DailyCandle 에서 KOSPI 최근 20봉 close 조회
        2. 현재가 vs 20MA 비교 · ±3% 이내면 choppy
        3. VKOSPI > 30 이면 crisis (승격)
    """
    # TODO(Phase 2 PIT): KOSPI DailyCandle 축적 후 자동 태깅 로직 활성
    return "unknown"
