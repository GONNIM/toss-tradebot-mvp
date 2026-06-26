"""네이버 금융 — 미국 주식 시총 리스트 페이지네이션.

URL: https://api.stock.naver.com/stock/exchange/{NASDAQ|NYSE}/marketValue?page=N&pageSize=100

시총 desc 정렬 → 시총 ≤ cap_max 인 종목만 필터.
무인증, 무료, 운영 IP 차단 없음 (이미 polling 사용 중).
"""
from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_LIST_BASE = "https://api.stock.naver.com/stock/exchange"
_PAGE_SIZE = 100
_TIMEOUT_SEC = 10.0
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class StockListing:
    reuters_code: str       # "AAPL.O" / "TSM"
    symbol: str             # "AAPL" / "TSM"
    name_kor: str
    name_eng: str
    exchange: str           # "NASDAQ" / "NYSE"
    industry_kor: Optional[str]
    market_value_usd: float
    close_price: Optional[float]


async def _fetch_page(
    exchange: str, page: int, client: httpx.AsyncClient
) -> dict:
    url = f"{_LIST_BASE}/{exchange}/marketValue"
    resp = await client.get(
        url,
        params={"page": page, "pageSize": _PAGE_SIZE},
        timeout=_TIMEOUT_SEC,
        headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    return _json.loads(resp.content.decode("cp949", errors="replace"))


async def fetch_us_listings(
    exchange: str, market_cap_max_usd: float
) -> list[StockListing]:
    """NASDAQ 또는 NYSE 시총 desc 페이지네이션 — cap_max 이하만 수집.

    desc 정렬 → 큰 시총 종목은 skip, cap_max 이하만 모음. totalCount 도달까지 순회.
    """
    results: list[StockListing] = []
    total: Optional[int] = None

    async with httpx.AsyncClient() as client:
        page = 1
        while True:
            try:
                data = await _fetch_page(exchange, page, client)
            except Exception as e:
                logger.warning(f"[naver_listing] {exchange} page {page} failed: {e}")
                break

            stocks = data.get("stocks") or []
            if not stocks:
                break
            if total is None:
                total = data.get("totalCount", 0)

            for s in stocks:
                cap_raw = s.get("marketValueRaw") or 0
                if cap_raw <= 0:
                    continue
                if cap_raw > market_cap_max_usd:
                    continue  # skip — desc 정렬이라 점차 줄어듦
                rc = s.get("reutersCode") or ""
                sym = s.get("symbolCode") or rc
                if not rc:
                    continue
                results.append(
                    StockListing(
                        reuters_code=rc,
                        symbol=sym,
                        name_kor=s.get("stockName") or "",
                        name_eng=s.get("stockNameEng") or "",
                        exchange=exchange,
                        industry_kor=(
                            (s.get("industryCodeType") or {}).get("industryGroupKor")
                        ),
                        market_value_usd=float(cap_raw),
                        close_price=(
                            float(s.get("closePriceRaw"))
                            if s.get("closePriceRaw") not in (None, "")
                            else None
                        ),
                    )
                )

            if total and page * _PAGE_SIZE >= total:
                break
            page += 1

    logger.info(
        f"[naver_listing] {exchange}: total={total}, "
        f"matched (cap ≤ ${market_cap_max_usd:,.0f}): {len(results)}"
    )
    return results
