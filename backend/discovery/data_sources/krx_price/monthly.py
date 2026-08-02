"""월봉·연봉 aggregate + 5MA rolling · Rulebook Phase E+ · 2026-08-02.

pykrx 는 일봉만 제공 · pandas resample 로 월/연 aggregate.

사용:
    from backend.discovery.data_sources.krx_price.monthly import (
        aggregate_monthly, aggregate_yearly, ma5_persistence, three_year_yoy,
    )

원칙: docs/operations/principles/johnma-8-fundamentals.md
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from backend.discovery.data_sources.krx_price.loader import fetch_daily_candles


async def _fetch_recent_daily(ticker: str, months: int) -> pd.DataFrame:
    """최근 N개월 일봉 · pykrx asyncio 래퍼 재사용."""
    today = date.today()
    # 여유롭게 (months + 3) 개월치 조회 · resample 안정성
    start = today.replace(day=1)
    # months+3 개월 전
    year, month = start.year, start.month
    total = year * 12 + (month - 1) - (months + 3)
    start = date(total // 12, total % 12 + 1, 1)
    return await fetch_daily_candles(ticker, start=start, end=today)


def aggregate_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 월봉 (월말 종가 기준)."""
    if daily.empty:
        return daily
    # loader 는 Index=날짜 · '종가' 컬럼 · resample 이 자동 처리
    monthly = daily["종가"].resample("MS").last().dropna()
    return monthly.to_frame("close")


def aggregate_yearly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 연봉 (연말 종가 기준)."""
    if daily.empty:
        return daily
    yearly = daily["종가"].resample("YS").last().dropna()
    return yearly.to_frame("close")


async def ma5_persistence(ticker: str) -> tuple[bool, int]:
    """월봉 5MA 위 3개월+ 유지 여부 판정 (단계 5).

    반환: (조건 충족 여부, 연속 유지 개월수)
    """
    daily = await _fetch_recent_daily(ticker, months=12)
    monthly = aggregate_monthly(daily)
    if len(monthly) < 8:
        # 최소 5MA(5) + 3개월 유지 = 8개월치 필요
        return (False, 0)

    monthly["ma5"] = monthly["close"].rolling(5).mean()
    valid = monthly.dropna(subset=["ma5"])
    if len(valid) < 3:
        return (False, 0)

    # 최근부터 역순으로 5MA 위 유지 개월수 카운트
    above_flags = (valid["close"] >= valid["ma5"]).tolist()
    count = 0
    for flag in reversed(above_flags):
        if flag:
            count += 1
        else:
            break
    return (count >= 3, count)


async def three_year_yoy(ticker: str) -> tuple[bool, list[float]]:
    """연봉 최근 3년 연평균 증가 판정 (단계 4 · 턴어라운드).

    Q3=A · 최근 3년 YoY 모두 양수 → 턴어라운드로 간주.
    반환: (조건 충족, [yoy_3y_ago, yoy_2y_ago, yoy_1y_ago])
    """
    daily = await _fetch_recent_daily(ticker, months=12 * 5)  # 5년치
    yearly = aggregate_yearly(daily)
    if len(yearly) < 4:
        return (False, [])

    # 최근 4개 연봉 · YoY 3개 계산
    tail = yearly["close"].tail(4).tolist()
    yoy = []
    for i in range(1, 4):
        prev, cur = tail[i - 1], tail[i]
        if prev <= 0:
            return (False, [])
        yoy.append((cur - prev) / prev)

    all_positive = all(y > 0 for y in yoy)
    return (all_positive, yoy)
