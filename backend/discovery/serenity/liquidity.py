"""유동성 (거래대금) 유틸 · Phase L14 · 2026-08-04.

RISK-PRINCIPLES §3 · ADV 20d ≥ $2M · 내 주문 / ADV ≤ 0.5% 필터 근거.

계산: Close × Volume · 20일 rolling mean.
"""
from __future__ import annotations

from typing import Optional


def compute_avg_dollar_volume(hist, *, window: int = 20) -> Optional[float]:
    """최근 window 거래일 평균 거래대금 (USD).

    hist: yfinance history() 결과 (Open/Close/Volume 컬럼 있는 pandas DataFrame).
    반환: 평균 USD (float) · 데이터 부족 시 None.
    """
    if hist is None or getattr(hist, "empty", True):
        return None
    try:
        recent = hist.tail(window)
        if len(recent) < window:
            return None
        dollar_volume = recent["Close"] * recent["Volume"]
        return float(dollar_volume.mean())
    except (KeyError, AttributeError, TypeError, ValueError):
        return None
