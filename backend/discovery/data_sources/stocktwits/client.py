"""Stocktwits 무인증 stream API — 종목 sentiment delta.

URL: https://api.stocktwits.com/api/2/streams/symbol/{TICKER}.json
Rate limit: 200 QPH 무인증 (200 / 3600s = ~3.3 QPM)

응답:
    {"messages": [
        {"id": ..., "entities": {"sentiment": {"basic": "Bullish"|"Bearish"|null}}}, ...
    ]}

sentiment_delta = (Bullish − Bearish) / total ∈ [-1, +1]
None (미표시) 메시지는 분모에서 제외 → 명시적으로 감정 표현한 메시지만 분석.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.stocktwits.com/api/2"
_UA = "toss-tradebot-mvp:meme-watch:v0.1"
_TIMEOUT_SEC = 10.0
_BETWEEN_REQ_SEC = 0.5  # 200 QPH = ~18s/req — 0.5s 마진 충분 (concurrency 5 와 함께)


@dataclass(frozen=True)
class StocktwitsSentiment:
    ticker: str
    total: int            # 분석 대상 messages (감정 표현된 것만)
    bullish: int
    bearish: int
    sentiment_delta: float    # (bullish - bearish) / total, 0 if total=0


async def _fetch_one(
    ticker: str, client: httpx.AsyncClient
) -> Optional[StocktwitsSentiment]:
    url = f"{_BASE}/streams/symbol/{ticker}.json"
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 422):
            # 종목 미등록 — silent skip
            return None
        logger.warning(f"[stocktwits] {ticker} HTTP {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[stocktwits] {ticker} failed: {e}")
        return None

    msgs = data.get("messages") or []
    bull, bear = 0, 0
    for m in msgs:
        sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        if sent == "Bullish":
            bull += 1
        elif sent == "Bearish":
            bear += 1
    total = bull + bear
    delta = (bull - bear) / total if total > 0 else 0.0
    return StocktwitsSentiment(
        ticker=ticker,
        total=total,
        bullish=bull,
        bearish=bear,
        sentiment_delta=delta,
    )


async def fetch_sentiment(ticker: str) -> Optional[StocktwitsSentiment]:
    """단일 ticker sentiment."""
    async with httpx.AsyncClient() as client:
        return await _fetch_one(ticker, client)


async def fetch_sentiment_batch(
    tickers: list[str], concurrency: int = 5
) -> dict[str, StocktwitsSentiment]:
    """다중 ticker — concurrency 제한 동시 호출 + sleep 안전 마진."""
    if not tickers:
        return {}
    result: dict[str, StocktwitsSentiment] = {}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        async def bounded(t: str) -> tuple[str, Optional[StocktwitsSentiment]]:
            async with sem:
                r = await _fetch_one(t, client)
                await asyncio.sleep(_BETWEEN_REQ_SEC)
                return t, r

        tasks = [bounded(t) for t in tickers]
        for fut in asyncio.as_completed(tasks):
            t, r = await fut
            if r is not None:
                result[t] = r

    logger.info(
        f"[stocktwits] batch: {len(result)} / {len(tickers)} success"
    )
    return result
