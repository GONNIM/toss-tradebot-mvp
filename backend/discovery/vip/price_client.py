"""네이버 US 실시간 quote — api.stock.naver.com/stock/{code}/basic.

실측 (2026-07-08~):
    delayTime = 0 (실시간)
    closePrice · fluctuationsRatio · marketStatus
    overMarketPriceInfo.fluctuationsRatio (AH/PM)
    stockItemTotalInfos — 시가/고가/저가·거래량/대금·시총·52주 고저·PER/EPS/PBR·배당 20개 지표
    itemLogoUrl · stockName · stockNameEng · industryCodeType·stockExchangeType

Why 별도 클라이언트: data_sources/naver_quote/client.py 는 KRX polling / foreign daily 담당.
US 실시간 basic 은 신규 — VIP 감시용.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.stock.naver.com/stock"
_TIMEOUT_SEC = 5.0
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class MarketStats:
    """Naver stockItemTotalInfos 20 지표 파싱 결과 (문자열 그대로 유지 — UI 표시용)."""
    base_price: Optional[str] = None            # 전일 종가
    open_price: Optional[str] = None
    high_price: Optional[str] = None
    low_price: Optional[str] = None
    accumulated_trading_volume: Optional[str] = None
    accumulated_trading_value: Optional[str] = None
    market_value: Optional[str] = None          # 시가총액
    industry_group_kor: Optional[str] = None
    high_52w: Optional[str] = None
    low_52w: Optional[str] = None
    per: Optional[str] = None
    eps: Optional[str] = None
    pbr: Optional[str] = None
    bps: Optional[str] = None
    dividend: Optional[str] = None
    dividend_yield_ratio: Optional[str] = None
    dividend_at: Optional[str] = None
    ex_dividend_at: Optional[str] = None
    face_value: Optional[str] = None
    face_value_division_rate: Optional[str] = None


@dataclass(frozen=True)
class UsQuote:
    ticker: str
    close_price: float                          # 정규장 마지막 체결가 (USD)
    fluctuations_ratio: float                   # 정규장 등락률 %
    compare_to_prev_close: Optional[float]      # 절대 변화 USD (신규)
    market_status: str                          # OPEN / CLOSE
    over_market_ratio: Optional[float]          # AH/PM 등락률 %
    local_traded_at: Optional[str]              # US local ISO
    # 신규 필드 (UI 개편)
    stock_name_kor: Optional[str] = None        # 한글명
    stock_name_eng: Optional[str] = None        # 영문명
    item_logo_url: Optional[str] = None         # 로고 URL
    exchange_name: Optional[str] = None         # NSQ/NYS 등
    market_stats: Optional[MarketStats] = None


# stockItemTotalInfos code → MarketStats field name 매핑
_STATS_CODE_MAP: Dict[str, str] = {
    "basePrice": "base_price",
    "openPrice": "open_price",
    "highPrice": "high_price",
    "lowPrice": "low_price",
    "accumulatedTradingVolume": "accumulated_trading_volume",
    "accumulatedTradingValue": "accumulated_trading_value",
    "marketValue": "market_value",
    "industryGroupKor": "industry_group_kor",
    "highPriceOf52Weeks": "high_52w",
    "lowPriceOf52Weeks": "low_52w",
    "per": "per",
    "eps": "eps",
    "pbr": "pbr",
    "bps": "bps",
    "dividend": "dividend",
    "dividendYieldRatio": "dividend_yield_ratio",
    "dividendAt": "dividend_at",
    "exDividendAt": "ex_dividend_at",
    "faceValue": "face_value",
    "faceValueDivisionRate": "face_value_division_rate",
}


def _parse_stats(items: list) -> MarketStats:
    kwargs: Dict[str, Optional[str]] = {}
    for it in items or []:
        code = str(it.get("code") or "")
        field_name = _STATS_CODE_MAP.get(code)
        if not field_name:
            continue
        val = it.get("value")
        if val is None or val == "" or str(val).strip().upper() == "N/A":
            continue
        kwargs[field_name] = str(val)
    return MarketStats(**kwargs)


async def fetch_us_quote(ticker: str) -> Optional[UsQuote]:
    """네이버 US 실시간 basic 1회 조회. 실패 시 None (호출자가 다음 tick 에서 재시도)."""
    url = f"{_BASE}/{ticker}/basic"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[vip.price] {ticker} fetch 실패: {e}")
        return None

    try:
        close_price = float(data["closePrice"])
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"[vip.price] {ticker} closePrice 파싱 실패: {e}")
        return None

    try:
        fluc_ratio = float(data.get("fluctuationsRatio") or 0.0)
    except (TypeError, ValueError):
        fluc_ratio = 0.0

    try:
        compare_prev = float(data.get("compareToPreviousClosePrice")) if data.get("compareToPreviousClosePrice") is not None else None
    except (TypeError, ValueError):
        compare_prev = None

    over = data.get("overMarketPriceInfo") or {}
    over_ratio: Optional[float] = None
    if over:
        try:
            over_ratio = float(over.get("fluctuationsRatio"))
        except (TypeError, ValueError):
            over_ratio = None

    exchange_type = data.get("stockExchangeType") or {}
    exchange_name = exchange_type.get("nameEng") or exchange_type.get("name")

    return UsQuote(
        ticker=ticker,
        close_price=close_price,
        fluctuations_ratio=fluc_ratio,
        compare_to_prev_close=compare_prev,
        market_status=str(data.get("marketStatus") or "").strip(),
        over_market_ratio=over_ratio,
        local_traded_at=data.get("localTradedAt"),
        stock_name_kor=data.get("stockName"),
        stock_name_eng=data.get("stockNameEng"),
        item_logo_url=data.get("itemLogoUrl"),
        exchange_name=exchange_name,
        market_stats=_parse_stats(data.get("stockItemTotalInfos") or []),
    )
