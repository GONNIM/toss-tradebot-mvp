"""Meme Intensity Index — 현재 폭등 강도 (Phase 3-E, 0~10).

Score(폭등 가능성 예측) 와 별개로 "실제 지금 얼마나 강하게 상승 중인가" 를
측정. 4지표 가중합 (score_delta 는 Phase 4 이력 테이블 필요).

이력 데이터 소스: MemeVolumeSnapshot (매일 daily batch).
샘플 부족 (신규 종목 등) 시 가용 지표만으로 부분 계산 → 시간 누적 후
자동 완성.

라벨:
  🌋 ERUPTING  (≥8.0) — 폭발적 상승, 즉시 결정 필요
  🚀 SURGING   (≥6.0) — 강한 상승 진행
  📈 RISING    (≥4.0) — 상승 추세
  〰️ STABILIZING (≥2.0) — 소강 국면
  💤 FLAT      (<2.0) — 강도 낮음
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.models import MemeVolumeSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntensityScore:
    ticker: str
    intensity: float          # 0 ~ 10
    label: str
    emoji: str
    # 원시 지표 값 (UI 세부 표시)
    return_1d: Optional[float]
    return_5d: Optional[float]
    acceleration: Optional[float]
    volume_ratio: Optional[float]
    sample_days: int          # 사용된 snapshot 개수


def _label_emoji(intensity: float) -> tuple[str, str]:
    if intensity >= 8.0:
        return "ERUPTING", "🌋"
    if intensity >= 6.0:
        return "SURGING", "🚀"
    if intensity >= 4.0:
        return "RISING", "📈"
    if intensity >= 2.0:
        return "STABILIZING", "〰️"
    return "FLAT", "💤"


def _norm_1d_return(r: Optional[float]) -> Optional[float]:
    """1D return → 0~10. 음수는 0."""
    if r is None:
        return None
    if r >= 30:
        return 10.0
    if r >= 20:
        return 8.0
    if r >= 10:
        return 6.0
    if r >= 5:
        return 4.0
    if r >= 0:
        return 2.0
    return 0.0


def _norm_acceleration(a: Optional[float]) -> Optional[float]:
    """가속도 (오늘 1D − 어제 1D) → 0~10.

    +20 = 급격한 반전 (어제 안 좋았는데 오늘 폭등).
    """
    if a is None:
        return None
    if a >= 20:
        return 10.0
    if a >= 10:
        return 8.0
    if a >= 5:
        return 6.0
    if a >= 0:
        return 4.0
    if a >= -5:
        return 2.0
    return 0.0


def _norm_5d_cumulative(c: Optional[float]) -> Optional[float]:
    """5일 누적 → 0~10."""
    if c is None:
        return None
    if c >= 50:
        return 10.0
    if c >= 30:
        return 8.0
    if c >= 15:
        return 6.0
    if c >= 5:
        return 4.0
    if c >= 0:
        return 2.0
    return 0.0


def _norm_volume_ratio(v: Optional[float]) -> Optional[float]:
    """거래량 배수 → 0~10."""
    if v is None or v <= 0:
        return None
    if v >= 10:
        return 10.0
    if v >= 5:
        return 8.0
    if v >= 3:
        return 6.0
    if v >= 2:
        return 4.0
    if v >= 1:
        return 2.0
    return 0.0


async def get_snapshot_history(
    session: AsyncSession, ticker: str, limit: int = 10
) -> list[MemeVolumeSnapshot]:
    """ticker 의 최근 N개 snapshot (오늘 → 과거)."""
    rows = (
        await session.execute(
            select(MemeVolumeSnapshot)
            .where(MemeVolumeSnapshot.ticker == ticker)
            .order_by(desc(MemeVolumeSnapshot.snapshot_at))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def compute_intensity(
    session: AsyncSession, ticker: str
) -> Optional[IntensityScore]:
    """4지표 가중합 → 0~10 intensity + 라벨.

    가중치: return_1d 0.30 · acceleration 0.30 · return_5d 0.20 · vol_ratio 0.20.
    (Phase 4 score_delta 도입 시: 0.25 / 0.25 / 0.15 / 0.15 / 0.20 재배분)
    """
    snapshots = await get_snapshot_history(session, ticker, limit=10)
    if not snapshots:
        return None

    latest = snapshots[0]
    today_r1d = latest.return_1d_pct
    today_ratio = latest.volume_ratio_20d

    # 어제 대비 acceleration
    accel: Optional[float] = None
    if len(snapshots) >= 2:
        yesterday = snapshots[1]
        if today_r1d is not None and yesterday.return_1d_pct is not None:
            accel = today_r1d - yesterday.return_1d_pct

    # 5일 누적 return
    r_5d: Optional[float] = None
    if len(snapshots) >= 5:
        five_ago = snapshots[4]
        if (
            latest.close is not None
            and five_ago.close is not None
            and five_ago.close > 0
        ):
            r_5d = (latest.close / five_ago.close - 1) * 100

    # 정규화 (None 지표는 가중치에서 제외)
    values = {
        "return_1d": (_norm_1d_return(today_r1d), 0.30),
        "acceleration": (_norm_acceleration(accel), 0.30),
        "return_5d": (_norm_5d_cumulative(r_5d), 0.20),
        "volume_ratio": (_norm_volume_ratio(today_ratio), 0.20),
    }

    weighted_sum = 0.0
    total_weight = 0.0
    for _, (n, w) in values.items():
        if n is None:
            continue
        weighted_sum += n * w
        total_weight += w

    if total_weight <= 0:
        return None
    intensity = weighted_sum / total_weight  # 재정규화 (가용 지표만)
    intensity = max(0.0, min(10.0, intensity))

    label, emoji = _label_emoji(intensity)

    return IntensityScore(
        ticker=ticker,
        intensity=intensity,
        label=label,
        emoji=emoji,
        return_1d=today_r1d,
        return_5d=r_5d,
        acceleration=accel,
        volume_ratio=today_ratio,
        sample_days=len(snapshots),
    )
