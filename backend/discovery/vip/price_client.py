"""네이버 US 실시간 quote — api.stock.naver.com/stock/{code}/basic.

실측 (2026-07-08):
    delayTime = 0 (실시간)
    closePrice, fluctuationsRatio, marketStatus
    overMarketPriceInfo.fluctuationsRatio (After-Hours / Pre-Market)

Why 별도 클라이언트: data_sources/naver_quote/client.py 는 KRX polling 및
foreign daily 담당. US 실시간 basic 엔드포인트는 신규 (P-B에서 peer /integration
로 확장 예정).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.stock.naver.com/stock"
_TIMEOUT_SEC = 5.0
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class UsQuote:
    ticker: str
    close_price: float           # 정규장 마지막 체결가 (USD)
    fluctuations_ratio: float    # 정규장 등락률 %
    market_status: str           # OPEN / CLOSE
    over_market_ratio: Optional[float]  # After-Hours or Pre-Market 등락률 %
    local_traded_at: Optional[str]      # 예: "20260707160000" (US local)


async def fetch_us_quote(ticker: str) -> Optional[UsQuote]:
    """WEN.O 등 네이버 US 실시간 quote 1회 조회.

    실패(네트워크·타임아웃·응답 파싱)는 None 반환 — 상위 루프가 다음 tick 에서 재시도.
    """
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

    over = data.get("overMarketPriceInfo") or {}
    over_ratio: Optional[float] = None
    if over:
        try:
            over_ratio = float(over.get("fluctuationsRatio"))
        except (TypeError, ValueError):
            over_ratio = None

    return UsQuote(
        ticker=ticker,
        close_price=close_price,
        fluctuations_ratio=fluc_ratio,
        market_status=str(data.get("marketStatus") or "").strip(),
        over_market_ratio=over_ratio,
        local_traded_at=data.get("localTradedAt"),
    )
