"""US universe 60일 일봉 fetch — 네이버 금융 기반 (yfinance 차단 우회).

운영 IP 가 Yahoo Finance 에 YFRateLimitError 로 차단되어, 이미 polling 으로
검증된 네이버 금융 API 로 전환. 종목별 호출 + concurrency 10.
"""
from __future__ import annotations

import logging

import pandas as pd

from backend.discovery.data_sources.naver_quote import fetch_daily_us_batch

logger = logging.getLogger(__name__)

_CONCURRENCY = 10


async def fetch_us_daily(
    tickers: list[str], period_days: int = 90
) -> dict[str, pd.DataFrame]:
    """US universe N일 일봉 (Close + Volume).

    Args:
        tickers: reuters_code 리스트 (예: "AAPL.O", "TSM").
        period_days: 일봉 days 범위 (주말/공휴일 고려 90일 기본 → ~60 거래일).

    Returns:
        {reuters_code: DataFrame[Close, Volume]} (asc 정렬, 결손 종목 누락).
    """
    if not tickers:
        return {}
    return await fetch_daily_us_batch(
        tickers, days_back=period_days, concurrency=_CONCURRENCY
    )
