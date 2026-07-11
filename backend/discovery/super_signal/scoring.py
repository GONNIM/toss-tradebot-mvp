"""Super Signal 스코어링 — v2 트랙 C Phase 3.

intensity = Σ(hit_score × source_weight)
- source_weight: activist(3.0) > vip(2.0) > meme_stock(1.0)
  · 근거: 활동주는 이벤트 확률과 배당 upside 최대 · VIP 는 감시 대상 확정성 · 밈은 변동성
"""
from __future__ import annotations

from typing import Iterable


SOURCE_WEIGHTS: dict[str, float] = {
    "activist": 3.0,
    "vip": 2.0,
    "meme_stock": 1.0,
}


def source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(source, 1.0)


def compute_intensity(hits: Iterable[dict]) -> float:
    """hits: [{"source": str, "score": float}, ...] → intensity."""
    total = 0.0
    for h in hits:
        w = source_weight(h.get("source", ""))
        s = float(h.get("score", 0.0))
        total += s * w
    return round(total, 4)


# 승격 임계값 (2+ source AND intensity ≥ 임계)
PROMOTE_MIN_SOURCES = 2
PROMOTE_MIN_INTENSITY = 1.5   # 예: activist 0.5 + vip 0.5 = 1.5 · 최소
