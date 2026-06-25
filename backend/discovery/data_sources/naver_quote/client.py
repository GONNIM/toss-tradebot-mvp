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

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://polling.finance.naver.com/api/realtime"
_TTL_SEC = 60
_TIMEOUT_SEC = 3.0
_BATCH_SIZE = 30  # 한 번 호출에 종목 수 상한 (URL 길이·서버 부하 균형)
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


async def _fetch_chunk(
    tickers: list[str], client: httpx.AsyncClient
) -> dict[str, Quote]:
    if not tickers:
        return {}
    query = ",".join(f"SERVICE_ITEM:{t}" for t in tickers)
    try:
        resp = await client.get(
            _BASE,
            params={"query": query},
            timeout=_TIMEOUT_SEC,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(
            f"[naver_quote] fetch failed for {len(tickers)} tickers: {e}"
        )
        return {}

    out: dict[str, Quote] = {}
    now = time.time()
    try:
        areas = data.get("result", {}).get("areas", [])
        for area in areas:
            for item in area.get("datas", []):
                cd = item.get("cd")
                nv = item.get("nv")
                if cd is None or nv is None:
                    continue
                try:
                    out[cd] = Quote(
                        ticker=cd,
                        current_price=float(nv),
                        prev_close=float(item["pcv"])
                        if item.get("pcv") is not None
                        else None,
                        change_rate=float(item["cr"])
                        if item.get("cr") is not None
                        else None,
                        market_status=item.get("ms"),
                        fetched_at=now,
                    )
                except (TypeError, ValueError) as e:
                    logger.warning(
                        f"[naver_quote] parse item {cd} failed: {e}"
                    )
    except (KeyError, TypeError) as e:
        logger.warning(f"[naver_quote] response shape unexpected: {e}")

    return out


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

    # 캐시 미스 분량 batch fetch
    async with httpx.AsyncClient() as client:
        for i in range(0, len(miss), _BATCH_SIZE):
            chunk = miss[i : i + _BATCH_SIZE]
            fetched = await _fetch_chunk(chunk, client)
            for t, q in fetched.items():
                _cache[t] = (q, now + _TTL_SEC)
                result[t] = q

    return result


async def fetch_one(ticker: str) -> Optional[Quote]:
    """단일 종목 — fetch_quotes 의 편의 wrapper."""
    quotes = await fetch_quotes([ticker])
    return quotes.get(_normalize(ticker))
