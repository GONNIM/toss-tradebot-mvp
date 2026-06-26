"""Google Trends — pytrends 무인증 (Captcha 회피 시간당 1회 권장).

API 한계: 한 호출에 keyword 5개. 시간당 호출 빈도 보수적 (~30회).
실패 시 graceful skip — Captcha 발생 시 1시간 backoff 권장.

검색량 정규화: 0~100 (Google 자체 정규화).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5
_BETWEEN_BATCH_SEC = 2.0
_TIMEFRAME = "now 1-d"   # 최근 1일
_GEO = "US"               # 미국 (Russell 2000 대응)


@dataclass(frozen=True)
class TrendSnapshot:
    ticker: str
    score_24h: int        # 0~100 정규화 검색량
    score_avg: float      # 24h 평균


def _sync_fetch_chunk(tickers: list[str]) -> dict[str, TrendSnapshot]:
    """pytrends 동기 호출 — asyncio.to_thread 로 래핑."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("[trends] pytrends 미설치 — skip")
        return {}

    out: dict[str, TrendSnapshot] = {}
    try:
        pytrends = TrendReq(hl="en-US", tz=300, timeout=(5, 10))
        pytrends.build_payload(
            kw_list=tickers, timeframe=_TIMEFRAME, geo=_GEO
        )
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return out
        for t in tickers:
            if t not in df.columns:
                continue
            series = df[t]
            score_24h = int(series.iloc[-1]) if len(series) else 0
            score_avg = float(series.mean()) if len(series) else 0.0
            out[t] = TrendSnapshot(
                ticker=t,
                score_24h=score_24h,
                score_avg=score_avg,
            )
    except Exception as e:
        logger.warning(f"[trends] chunk {tickers} failed: {e}")
    return out


async def fetch_interest(tickers: list[str]) -> dict[str, TrendSnapshot]:
    """다중 ticker — 5개씩 chunk + 2초 sleep (rate limit 안전)."""
    if not tickers:
        return {}
    result: dict[str, TrendSnapshot] = {}
    for i in range(0, len(tickers), _BATCH_SIZE):
        chunk = tickers[i : i + _BATCH_SIZE]
        fetched = await asyncio.to_thread(_sync_fetch_chunk, chunk)
        result.update(fetched)
        if i + _BATCH_SIZE < len(tickers):
            await asyncio.sleep(_BETWEEN_BATCH_SEC)
    logger.info(f"[trends] fetched: {len(result)} / {len(tickers)}")
    return result
