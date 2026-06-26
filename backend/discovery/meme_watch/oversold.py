"""기술적 지표 — RSI(14) + 거래량 z-score(20D) + 1D 수익률.

설계: docs/plans/meme-stock-discovery/02-confluence-design.md §2.3~2.4
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def compute_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
    """단순 EMA 기반 RSI(14) — 마지막 값만 반환."""
    if closes is None or len(closes) < period + 1:
        return None
    delta = closes.astype(float).diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - 100 / (1 + rs)
    if rsi.empty or pd.isna(rsi.iloc[-1]):
        return None
    return float(rsi.iloc[-1])


def compute_volume_z(volumes: pd.Series, window: int = 20) -> Optional[float]:
    """20일 거래량 평균·표준편차 대비 당일 z-score."""
    if volumes is None or len(volumes) < window + 1:
        return None
    recent = float(volumes.iloc[-1])
    history = volumes.iloc[-(window + 1) : -1].astype(float)
    mean = history.mean()
    std = history.std()
    if not std or std == 0 or pd.isna(std):
        return 0.0
    return float((recent - mean) / std)


def compute_volume_ratio(volumes: pd.Series, window: int = 20) -> Optional[float]:
    """20일 거래량 평균 대비 당일 배수 (Phase 2 튜닝).

    z-score 가 폭증 누적 시 std 폭증으로 무뎌지는 문제 해결.
    예: 거래량 1억주, 20D 평균 1천만주 → ratio = 10 (선형 표현).
    """
    if volumes is None or len(volumes) < window + 1:
        return None
    recent = float(volumes.iloc[-1])
    history = volumes.iloc[-(window + 1) : -1].astype(float)
    mean = history.mean()
    if not mean or mean <= 0 or pd.isna(mean):
        return None
    return float(recent / mean)


def compute_return_1d(closes: pd.Series) -> Optional[float]:
    """1일 수익률 (% 단위)."""
    if closes is None or len(closes) < 2:
        return None
    prev = float(closes.iloc[-2])
    curr = float(closes.iloc[-1])
    if prev <= 0:
        return None
    return (curr / prev - 1) * 100
