"""Stooq 클라이언트 — Discovery 가격 데이터 1차 소스 (결정 15·23·45).

- 무료, API key 불필요
- 전체 미국 종목 커버
- 일봉 직접 제공 (52w high/low 자체 계산 가능)
- CSV 다운로드 방식

URL 패턴: https://stooq.com/q/d/l/?s={ticker}.us&i=d  (NASDAQ 종목)
응답: CSV (Date,Open,High,Low,Close,Volume)
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime

from backend.discovery.data_sources.base import DataSourceClient, DataSourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candle:
    """일봉 데이터."""

    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class FiftyTwoWeekStats:
    """52주 통계."""

    ticker: str
    high: float
    low: float
    high_date: str
    low_date: str
    current_price: float
    pct_from_high: float  # (current - high) / high (음수)
    pct_from_low: float   # (current - low) / low (양수)


class StooqClient(DataSourceClient):
    """Stooq 일봉 데이터 클라이언트."""

    BASE_URL = "https://stooq.com"

    def __init__(self) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            headers={
                "User-Agent": "toss-tradebot-mvp/0.1 (https://github.com/...)",
            },
        )

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        """Stooq 티커 정규화.

        - US 종목: 소문자 + '.us' suffix (예: AAPL → aapl.us)
        - 이미 suffix 있으면 그대로
        """
        t = ticker.lower().strip()
        if "." not in t:
            t = f"{t}.us"
        return t

    async def get_daily_candles(
        self,
        ticker: str,
        count: int | None = None,
    ) -> list[Candle]:
        """일봉 데이터 조회 (CSV 다운로드).

        Args:
            ticker: 'AAPL' 또는 'aapl.us'
            count: 반환 캔들 수 (None=전체, 보통 252 = 1년)

        Returns:
            list[Candle] — 날짜 오름차순 (오래된 → 최신)

        Raises:
            DataSourceError: HTTP 오류 또는 빈 응답
        """
        symbol = self._normalize_ticker(ticker)
        response = await self.get(
            "/q/d/l/",
            params={"s": symbol, "i": "d"},  # i=d → daily
        )

        text = response.text.strip()
        if not text or text.startswith("<") or "No data" in text:
            raise DataSourceError(f"Stooq: no data for {symbol}")

        candles: list[Candle] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                candles.append(
                    Candle(
                        date=row["Date"],
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(float(row["Volume"])) if row.get("Volume") else 0,
                    )
                )
            except (ValueError, KeyError) as e:
                logger.warning(f"[Stooq] {symbol} skip bad row {row}: {e}")
                continue

        if not candles:
            raise DataSourceError(f"Stooq: parsed 0 candles for {symbol}")

        candles.sort(key=lambda c: c.date)
        if count is not None:
            candles = candles[-count:]

        logger.info(f"[Stooq] {symbol} {len(candles)} candles ({candles[0].date} ~ {candles[-1].date})")
        return candles

    async def get_52w_stats(self, ticker: str) -> FiftyTwoWeekStats:
        """52주 고가/저가 + 현재가 + 백분율 계산.

        Discovery 모듈의 핵심 입력 (결정 23 Stooq 직접 제공).
        """
        candles = await self.get_daily_candles(ticker, count=252)
        if not candles:
            raise DataSourceError(f"Stooq: 52w stats unavailable for {ticker}")

        highest = max(candles, key=lambda c: c.high)
        lowest = min(candles, key=lambda c: c.low)
        current = candles[-1].close

        return FiftyTwoWeekStats(
            ticker=ticker.upper(),
            high=highest.high,
            low=lowest.low,
            high_date=highest.date,
            low_date=lowest.date,
            current_price=current,
            pct_from_high=(current - highest.high) / highest.high,
            pct_from_low=(current - lowest.low) / lowest.low,
        )

    async def get_current_price(self, ticker: str) -> float:
        """최근 종가만 빠르게 조회.

        Note: Stooq 는 실시간 X — 5분 ~ 60분 지연 가능.
        """
        candles = await self.get_daily_candles(ticker, count=1)
        if not candles:
            raise DataSourceError(f"Stooq: current price unavailable for {ticker}")
        return candles[-1].close

    async def get_returns(
        self,
        ticker: str,
        periods: tuple[int, ...] = (21, 63, 126),  # ~1m, 3m, 6m 거래일
    ) -> dict[str, float]:
        """기간별 수익률 계산 (Crazy Picks 가격 모멘텀 인자용).

        Returns:
            {'1m': 0.05, '3m': 0.12, '6m': 0.30} 같은 dict
            거래일 252 = 1년
        """
        max_days = max(periods)
        candles = await self.get_daily_candles(ticker, count=max_days + 1)
        if len(candles) < max_days + 1:
            logger.warning(f"[Stooq] {ticker} only {len(candles)} candles, max requested {max_days+1}")

        labels = {21: "1m", 63: "3m", 126: "6m", 252: "1y"}
        current = candles[-1].close
        returns: dict[str, float] = {}
        for n in periods:
            if len(candles) <= n:
                returns[labels.get(n, f"{n}d")] = 0.0
                continue
            past = candles[-1 - n].close
            returns[labels.get(n, f"{n}d")] = (current - past) / past if past > 0 else 0.0

        return returns
