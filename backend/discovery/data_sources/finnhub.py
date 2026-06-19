"""Finnhub Free Tier 클라이언트 — Discovery 어닝·애널리스트 데이터.

- 무료 60 req/min
- API key 필수 (.env FINNHUB_API_KEY)
- 어닝 캘린더·EPS·애널리스트 추천·회사 정보

결정 14·45 — Crazy Picks 어닝 모멘텀 (20% 가중) 핵심 소스.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from backend.discovery.data_sources.base import DataSourceClient, DataSourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EarningsEvent:
    """어닝 발표 일정."""

    ticker: str
    date: str         # YYYY-MM-DD
    time: str         # 'bmo' (before market open) / 'amc' (after market close) / 'dmh'
    eps_estimate: Optional[float]
    eps_actual: Optional[float]
    revenue_estimate: Optional[float]
    revenue_actual: Optional[float]
    quarter: Optional[int]
    year: Optional[int]


@dataclass(frozen=True)
class CompanyProfile:
    """회사 정보 (시총·섹터)."""

    ticker: str
    name: str
    market_cap: Optional[float]   # in millions
    sector: Optional[str]
    industry: Optional[str]
    exchange: Optional[str]
    country: Optional[str]
    ipo_date: Optional[str]
    shares_outstanding: Optional[float]


@dataclass(frozen=True)
class AnalystRecommendation:
    """애널리스트 추천 분포."""

    ticker: str
    period: str            # YYYY-MM
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int


class FinnhubClient(DataSourceClient):
    """Finnhub Free Tier 클라이언트."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        if not key:
            logger.warning(
                "[Finnhub] FINNHUB_API_KEY 미설정 — 호출 시 401 예상. "
                ".env 에 키 추가 필요 (finnhub.io 무료 가입)"
            )
        super().__init__(
            base_url=self.BASE_URL,
            headers={"X-Finnhub-Token": key} if key else {},
        )
        self.api_key = key

    async def get_earnings_calendar(
        self,
        from_date: str,
        to_date: str,
        ticker: Optional[str] = None,
    ) -> list[EarningsEvent]:
        """어닝 캘린더 조회.

        Args:
            from_date: 'YYYY-MM-DD'
            to_date: 'YYYY-MM-DD'
            ticker: 특정 종목만 (None=전체 시장)
        """
        params: dict[str, str] = {"from": from_date, "to": to_date}
        if ticker:
            params["symbol"] = ticker.upper()

        response = await self.get("/calendar/earnings", params=params)
        data = response.json()
        events_raw = data.get("earningsCalendar", []) or []

        events: list[EarningsEvent] = []
        for e in events_raw:
            events.append(
                EarningsEvent(
                    ticker=e.get("symbol", "").upper(),
                    date=e.get("date", ""),
                    time=e.get("hour", "") or "",
                    eps_estimate=e.get("epsEstimate"),
                    eps_actual=e.get("epsActual"),
                    revenue_estimate=e.get("revenueEstimate"),
                    revenue_actual=e.get("revenueActual"),
                    quarter=e.get("quarter"),
                    year=e.get("year"),
                )
            )

        logger.info(f"[Finnhub] earnings {from_date}~{to_date}: {len(events)} events")
        return events

    async def get_company_profile(self, ticker: str) -> CompanyProfile:
        """회사 정보 (시총·섹터·IPO·발행주식)."""
        response = await self.get(
            "/stock/profile2",
            params={"symbol": ticker.upper()},
        )
        data = response.json()
        if not data or not data.get("ticker"):
            raise DataSourceError(f"Finnhub: profile not found for {ticker}")

        return CompanyProfile(
            ticker=data["ticker"].upper(),
            name=data.get("name", ""),
            market_cap=data.get("marketCapitalization"),
            sector=data.get("finnhubIndustry"),
            industry=data.get("finnhubIndustry"),
            exchange=data.get("exchange"),
            country=data.get("country"),
            ipo_date=data.get("ipo"),
            shares_outstanding=data.get("shareOutstanding"),
        )

    async def get_analyst_recommendations(
        self,
        ticker: str,
    ) -> list[AnalystRecommendation]:
        """애널리스트 추천 분포 (최근 4분기)."""
        response = await self.get(
            "/stock/recommendation",
            params={"symbol": ticker.upper()},
        )
        data = response.json()
        if not data:
            return []

        return [
            AnalystRecommendation(
                ticker=ticker.upper(),
                period=r.get("period", ""),
                strong_buy=r.get("strongBuy", 0),
                buy=r.get("buy", 0),
                hold=r.get("hold", 0),
                sell=r.get("sell", 0),
                strong_sell=r.get("strongSell", 0),
            )
            for r in data
        ]

    async def get_eps_surprise_history(
        self,
        ticker: str,
        limit: int = 4,
    ) -> list[dict]:
        """어닝 서프라이즈 이력 (PEAD 계산 기반, 결정 14).

        Returns:
            [{'period': '2026-03-31', 'actual': 1.23, 'estimate': 1.10, 'surprise': 11.8, ...}, ...]
        """
        response = await self.get(
            "/stock/earnings",
            params={"symbol": ticker.upper(), "limit": limit},
        )
        return response.json() or []
