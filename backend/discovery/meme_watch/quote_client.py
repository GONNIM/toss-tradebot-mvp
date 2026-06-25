"""yfinance bulk 일봉 fetch — US universe 60일 close + volume.

Phase 1b MVP — US Russell 2000 일배치. KRX 일봉은 Phase 1b-bonus 또는
Phase 2 (pykrx 통합).
"""
from __future__ import annotations

import asyncio
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CHUNK = 100   # yfinance bulk 안전 chunk (URL 길이·rate limit 균형)


def _sync_bulk_download(tickers: list[str], period_days: int) -> dict[str, pd.DataFrame]:
    """yfinance.download 동기 호출 — asyncio.to_thread 로 래핑됨."""
    out: dict[str, pd.DataFrame] = {}
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period=f"{period_days}d",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )
        if data is None or data.empty:
            return out
        if len(tickers) == 1:
            t = tickers[0]
            sub = data[["Close", "Volume"]].dropna()
            if not sub.empty:
                out[t] = sub
        else:
            for t in tickers:
                try:
                    sub = data[t][["Close", "Volume"]].dropna()
                    if not sub.empty:
                        out[t] = sub
                except (KeyError, ValueError, IndexError):
                    pass
    except Exception as e:
        logger.warning(f"[quote_client] yf.download chunk ({len(tickers)} tickers) failed: {e}")
    return out


async def fetch_us_daily(
    tickers: list[str], period_days: int = 60
) -> dict[str, pd.DataFrame]:
    """US universe 60일 일봉 (close + volume) — chunked bulk.

    Returns:
        {ticker: DataFrame[Close, Volume]} (date 정렬, 결손 종목은 누락).
    """
    if not tickers:
        return {}

    result: dict[str, pd.DataFrame] = {}
    total_chunks = (len(tickers) + _CHUNK - 1) // _CHUNK

    for i in range(0, len(tickers), _CHUNK):
        chunk = tickers[i : i + _CHUNK]
        fetched = await asyncio.to_thread(_sync_bulk_download, chunk, period_days)
        result.update(fetched)
        chunk_idx = i // _CHUNK + 1
        logger.info(
            f"[quote_client] chunk {chunk_idx}/{total_chunks} "
            f"({len(chunk)} req → {len(fetched)} got)"
        )

    logger.info(
        f"[quote_client] US daily fetch: {len(result)} / {len(tickers)} tickers"
    )
    return result
