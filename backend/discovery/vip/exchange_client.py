"""네이버 환율 (USD→KRW) — 하루 1회 캐시.

`api.stock.naver.com/marketindex/exchange/FX_USDKRW` 하나은행 실시간 고시.
1일 갱신이면 P&L 표시엔 충분. 서버 부담 최소.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_URL = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"
_TIMEOUT_SEC = 5.0
_TTL_SEC = 24 * 3600  # 1일
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class UsdKrwRate:
    rate: float                   # 1 USD 당 KRW
    fluctuations_ratio: float     # 전일 대비 등락률 %
    fetched_at: float             # unix
    source: str = "Naver (Hana Bank)"


_cache: Optional[UsdKrwRate] = None
_cache_at: float = 0.0


async def fetch_usd_krw() -> Optional[UsdKrwRate]:
    """USD→KRW 환율 (하루 1회 캐시). 실패 시 이전 캐시 반환, 캐시도 없으면 None."""
    global _cache, _cache_at
    now = time.time()

    if _cache is not None and (now - _cache_at) < _TTL_SEC:
        return _cache

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(_URL, headers={"User-Agent": _UA})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[vip.fx] USD/KRW fetch 실패: {e}")
        return _cache  # stale 이라도 있으면 반환

    info = data.get("exchangeInfo") or {}
    try:
        rate = float(str(info.get("closePrice", "")).replace(",", ""))
    except (TypeError, ValueError):
        logger.warning(f"[vip.fx] closePrice 파싱 실패: {info.get('closePrice')!r}")
        return _cache

    try:
        fluc = float(str(info.get("fluctuationsRatio", "0")).replace(",", ""))
    except (TypeError, ValueError):
        fluc = 0.0

    _cache = UsdKrwRate(rate=rate, fluctuations_ratio=fluc, fetched_at=now)
    _cache_at = now
    return _cache
