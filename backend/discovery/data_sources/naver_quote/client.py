"""네이버 금융 polling API — 실시간 현재가 (무인증, 무료).

URL:
    https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:000660,SERVICE_ITEM:005930

응답 (단일 종목 예):
    {
      "result": {
        "areas": [{"datas": [{
          "cd": "000660", "nv": 2917000, "pcv": 2580000,
          "cr": 13.06, "ms": "CLOSE", ...
        }]}]
      }
    }

필드:
    cd  = KRX 종목 코드
    nv  = 현재가 (net value)
    pcv = 전일 종가
    cr  = 변화율 %
    ms  = 장 상태 (OPEN / CLOSE)

장 마감 후엔 nv = pcv (당일 종가).

Why: KrxStockMeta.last_close 는 매일 야간 갱신이라 장중·실시간 가격과 차이.
사용자가 보는 "현재가"는 실제 시세여야 함.

How to apply: fetch_quotes(tickers) → 60초 메모리 캐시 → 호출자는 fallback 보유.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://polling.finance.naver.com/api/realtime"
_DAILY_BASE = "https://api.stock.naver.com/chart"  # /foreign/item/{rc}/day, /domestic/item/{t}/day
_TTL_SEC = 60
_TIMEOUT_SEC = 3.0
_DAILY_TIMEOUT_SEC = 10.0
_CONCURRENCY = 10  # 동시 요청 상한 (네이버 부담·응답 속도 균형)
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# in-memory 캐시: {ticker: (Quote, expires_at_unix)}
_cache: dict[str, tuple["Quote", float]] = {}


@dataclass(frozen=True)
class Quote:
    ticker: str
    current_price: float
    prev_close: Optional[float]
    change_rate: Optional[float]
    market_status: Optional[str]  # OPEN / CLOSE
    fetched_at: float  # unix timestamp


def _normalize(ticker: str) -> str:
    """KRX 종목 코드를 6자리 0-패딩 문자열로."""
    return str(ticker).zfill(6)


def _read_cache(ticker: str, now: float) -> Optional[Quote]:
    entry = _cache.get(ticker)
    if entry is None:
        return None
    q, exp = entry
    if now >= exp:
        return None
    return q


async def _fetch_one_internal(
    ticker: str, client: httpx.AsyncClient
) -> Optional[Quote]:
    """단일 종목 호출 — 네이버 polling 은 batch query 미지원 (첫 종목만 응답)."""
    try:
        resp = await client.get(
            _BASE,
            params={"query": f"SERVICE_ITEM:{ticker}"},
            timeout=_TIMEOUT_SEC,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        # 네이버 polling 응답은 CP949 (한글 종목명) — utf-8 자동 디코딩 실패.
        # nm 필드는 안 쓰지만 json.loads 가 전체 문자열을 디코딩하므로 한 글자라도 깨지면 실패.
        data = _json.loads(resp.content.decode("cp949", errors="replace"))
    except Exception as e:
        logger.warning(f"[naver_quote] fetch {ticker} failed: {e}")
        return None

    try:
        areas = data.get("result", {}).get("areas", [])
        for area in areas:
            for item in area.get("datas", []):
                cd = item.get("cd")
                nv = item.get("nv")
                if cd is None or nv is None:
                    continue
                if cd != ticker:
                    continue
                return Quote(
                    ticker=cd,
                    current_price=float(nv),
                    prev_close=float(item["pcv"])
                    if item.get("pcv") is not None
                    else None,
                    change_rate=float(item["cr"])
                    if item.get("cr") is not None
                    else None,
                    market_status=item.get("ms"),
                    fetched_at=time.time(),
                )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"[naver_quote] parse {ticker} failed: {e}")
    return None


async def fetch_quotes(tickers: list[str]) -> dict[str, Quote]:
    """여러 종목의 현재가를 한 번에 fetch (60초 캐시, batch).

    Args:
        tickers: KRX 6자리 종목 코드 (예: ['000660', '005930']).

    Returns:
        {ticker: Quote}. fetch 실패한 종목은 dict 에 포함되지 않음.
        호출자는 fallback 처리 책임.
    """
    if not tickers:
        return {}

    now = time.time()
    normalized = [_normalize(t) for t in tickers]

    # 캐시 hit / miss 분리
    result: dict[str, Quote] = {}
    miss: list[str] = []
    for t in normalized:
        cached = _read_cache(t, now)
        if cached is not None:
            result[t] = cached
        else:
            miss.append(t)

    if not miss:
        return result

    # 캐시 미스 종목 — concurrency 제한 하에 동시 호출
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient() as client:
        async def bounded(t: str) -> tuple[str, Optional[Quote]]:
            async with sem:
                return t, await _fetch_one_internal(t, client)

        tasks = [bounded(t) for t in miss]
        for fut in asyncio.as_completed(tasks):
            t, q = await fut
            if q is not None:
                _cache[t] = (q, now + _TTL_SEC)
                result[t] = q

    return result


async def fetch_one(ticker: str) -> Optional[Quote]:
    """단일 종목 — fetch_quotes 의 편의 wrapper."""
    quotes = await fetch_quotes([ticker])
    return quotes.get(_normalize(ticker))


# ─────────────────────────────────────────────────────────────────
# 일봉 fetch — Meme Watch Phase 1b 용 (yfinance 차단 우회)
# ─────────────────────────────────────────────────────────────────

import pandas as pd  # noqa: E402 — 일봉 함수에서만 사용


def _date_range_params(days_back: int) -> dict:
    """startDateTime / endDateTime — 오늘 기준 N일 전 ~ 오늘."""
    from datetime import datetime, timedelta
    end = datetime.now()
    start = end - timedelta(days=days_back)
    return {
        "startDateTime": start.strftime("%Y%m%d0000"),
        "endDateTime": end.strftime("%Y%m%d2359"),
    }


async def _fetch_daily_naver(
    path: str, identifier: str, days_back: int, client: httpx.AsyncClient
) -> Optional[pd.DataFrame]:
    """공통 일봉 fetcher.

    path: "foreign" (미국) | "domestic" (한국)
    identifier: "AAPL.O" | "005930"
    """
    url = f"{_DAILY_BASE}/{path}/item/{identifier}/day"
    try:
        resp = await client.get(
            url,
            params=_date_range_params(days_back),
            timeout=_DAILY_TIMEOUT_SEC,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        data = _json.loads(resp.content.decode("cp949", errors="replace"))
    except Exception as e:
        logger.warning(f"[naver_daily] {identifier} failed: {e}")
        return None

    if not data:
        return None
    try:
        df = pd.DataFrame(data)
        df["Date"] = pd.to_datetime(df["localDate"], format="%Y%m%d")
        df["Close"] = df["closePrice"].astype(float)
        df["Volume"] = df["accumulatedTradingVolume"].astype(float)
        df = df.set_index("Date").sort_index()
        return df[["Close", "Volume"]]
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"[naver_daily] {identifier} parse failed: {e}")
        return None


async def fetch_daily_us(
    reuters_code: str, days_back: int = 90
) -> Optional[pd.DataFrame]:
    """미국 종목 일봉 — DataFrame[Close, Volume]. asc 정렬."""
    async with httpx.AsyncClient() as client:
        return await _fetch_daily_naver("foreign", reuters_code, days_back, client)


async def fetch_daily_kr(
    ticker: str, days_back: int = 90
) -> Optional[pd.DataFrame]:
    """한국 종목 일봉 — 6자리 ticker. DataFrame[Close, Volume]. asc 정렬."""
    async with httpx.AsyncClient() as client:
        return await _fetch_daily_naver("domestic", _normalize(ticker), days_back, client)


async def fetch_daily_us_batch(
    reuters_codes: list[str], days_back: int = 90, concurrency: int = 10
) -> dict[str, pd.DataFrame]:
    """US 종목 batch 일봉 — concurrency 제한 동시 호출."""
    if not reuters_codes:
        return {}
    result: dict[str, pd.DataFrame] = {}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        async def bounded(rc: str) -> tuple[str, Optional[pd.DataFrame]]:
            async with sem:
                df = await _fetch_daily_naver("foreign", rc, days_back, client)
                return rc, df

        tasks = [bounded(rc) for rc in reuters_codes]
        completed = 0
        for fut in asyncio.as_completed(tasks):
            rc, df = await fut
            completed += 1
            if df is not None and not df.empty:
                result[rc] = df
            if completed % 200 == 0:
                logger.info(
                    f"[naver_daily_batch] {completed}/{len(reuters_codes)} processed, "
                    f"{len(result)} success"
                )

    logger.info(
        f"[naver_daily_batch] done: {len(result)} / {len(reuters_codes)} success"
    )
    return result
