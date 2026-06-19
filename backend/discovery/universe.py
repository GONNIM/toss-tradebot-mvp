"""Ticker universe — 미국 주식 후보 집합.

Crazy universe (시총 ≥ $1B):
  - S&P 500 + Nasdaq 100 + 대형주 ETF 보유 종목 → 약 1,500 종목
  - SEC company tickers JSON 활용 + Finnhub profile market_cap 필터

Moonshot universe (모든 미국 주식):
  - 가격 ≥ $0.10
  - 일평균 거래량 ≥ 500K
  - NYSE/NASDAQ 상장
  - 상장 30일 이상
  → 약 7,000 종목

캐시 전략:
  - `ticker_universe` 테이블에 일일 저장
  - 매일 06:00 KST 갱신 (Crazy + Moonshot 동시 갱신)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerInfo:
    """ticker_universe 테이블 row."""

    ticker: str
    name: str
    exchange: str               # NASDAQ / NYSE / AMEX
    sector: Optional[str]
    market_cap_usd: Optional[float]
    avg_daily_volume_20d: Optional[float]
    current_price: Optional[float]
    listing_date: Optional[str]
    risk_level: str             # HIGH/MED/LOW (scoring.classify_risk)
    is_crazy: bool              # 시총 ≥ $1B
    is_moonshot: bool           # 모든 US stocks 기본 통과 종목


# Crazy universe minimum filter
CRAZY_MIN_MARKET_CAP = 1_000_000_000  # $1B
# Moonshot universe minimum filter
MOONSHOT_MIN_PRICE = 0.10
MOONSHOT_MIN_AVG_VOLUME = 500_000
MOONSHOT_MIN_LISTING_DAYS = 30


def passes_crazy_filter(info: TickerInfo) -> bool:
    """Crazy 모듈 universe 필터."""
    if info.market_cap_usd is None:
        return False
    if info.market_cap_usd < CRAZY_MIN_MARKET_CAP:
        return False
    if info.current_price is None or info.current_price < 1.0:
        return False
    return True


def passes_moonshot_filter(info: TickerInfo) -> bool:
    """Moonshot 모듈 universe 필터."""
    if info.current_price is None or info.current_price < MOONSHOT_MIN_PRICE:
        return False
    if info.avg_daily_volume_20d is None or info.avg_daily_volume_20d < MOONSHOT_MIN_AVG_VOLUME:
        return False
    if info.exchange not in ("NASDAQ", "NYSE", "AMEX"):
        return False
    return True


async def load_initial_universe_from_sec() -> list[TickerInfo]:
    """SEC company_tickers.json → 초기 universe (메타데이터만).

    Phase D 후속 — Finnhub profile + Stooq quote 결합해 풍성화.
    현재는 ticker + name + 빈 메타데이터.
    """
    from backend.discovery.data_sources.sec_edgar import SECEdgarClient

    universe: list[TickerInfo] = []
    async with SECEdgarClient() as client:
        mapping = await client._load_ticker_map()
        for ticker in mapping.keys():
            universe.append(
                TickerInfo(
                    ticker=ticker,
                    name="",  # Phase D 에서 Finnhub 으로 채움
                    exchange="UNKNOWN",
                    sector=None,
                    market_cap_usd=None,
                    avg_daily_volume_20d=None,
                    current_price=None,
                    listing_date=None,
                    risk_level="MED",
                    is_crazy=False,
                    is_moonshot=False,
                )
            )

    logger.info(f"[Universe] loaded {len(universe)} tickers from SEC")
    return universe


async def enrich_ticker(
    ticker: str,
    finnhub_client,  # FinnhubClient
    stooq_client,    # StooqClient
) -> Optional[TickerInfo]:
    """ticker → Finnhub profile + Stooq 가격/거래량 결합.

    Returns:
        None if any critical data missing (graceful skip).
    """
    from backend.discovery.scoring import classify_risk

    try:
        profile = await finnhub_client.get_company_profile(ticker)
    except Exception as e:
        logger.debug(f"[Universe] {ticker} profile fetch failed: {e}")
        return None

    try:
        candles = await stooq_client.get_daily_candles(ticker, count=30)
        if not candles:
            return None
        current = candles[-1]
        avg_vol = sum(c.volume for c in candles) / len(candles)
    except Exception as e:
        logger.debug(f"[Universe] {ticker} stooq fetch failed: {e}")
        return None

    mcap_usd = (profile.market_cap or 0) * 1_000_000
    risk = classify_risk(mcap_usd, current.close)

    info = TickerInfo(
        ticker=ticker.upper(),
        name=profile.name or "",
        exchange=profile.exchange or "UNKNOWN",
        sector=profile.sector,
        market_cap_usd=mcap_usd if mcap_usd > 0 else None,
        avg_daily_volume_20d=avg_vol,
        current_price=current.close,
        listing_date=profile.ipo_date,
        risk_level=risk,
        is_crazy=False,  # passes_crazy_filter 후 set
        is_moonshot=False,
    )
    return TickerInfo(
        **{**info.__dict__, "is_crazy": passes_crazy_filter(info), "is_moonshot": passes_moonshot_filter(info)}
    )
