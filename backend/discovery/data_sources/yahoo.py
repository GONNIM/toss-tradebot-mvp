"""Yahoo Finance 클라이언트 — 가격·52w·수익률 (Stooq 대체, 결정 2026-06-20).

배경:
- Stooq 가 JS PoW 봇 차단 도입 (2026-06-20 발견) → 무인증 HTTP GET 불가
- Yahoo Finance 는 yfinance 라이브러리로 안정 접근, 무료·무인증·rate limit 관용적

설계:
- StooqClient 와 동일 인터페이스 (Candle, FiftyTwoWeekStats 재사용)
- yfinance 는 sync — asyncio.to_thread 로 wrap
- 의존성: yfinance>=0.2.40 (pyproject.toml 에 추가 필요)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.discovery.data_sources.stooq import Candle, FiftyTwoWeekStats

logger = logging.getLogger(__name__)


class YahooClient:
    """yfinance 기반 일봉 클라이언트.

    Stooq 와 동일 메서드 시그니처 — drop-in 대체 가능.
    """

    def __init__(self) -> None:
        self._yf = None  # yfinance module, lazy

    async def __aenter__(self) -> "YahooClient":
        try:
            import yfinance as yf
        except ImportError as e:
            raise RuntimeError("yfinance 미설치. `pip install yfinance`") from e
        self._yf = yf
        return self

    async def __aexit__(self, *exc) -> None:
        self._yf = None

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        """Yahoo 는 plain symbol (AAPL, MSFT)."""
        return ticker.upper().strip()

    def _fetch_history_sync(self, ticker: str, count: int) -> list[Candle]:
        """sync — asyncio.to_thread 로 호출."""
        symbol = self._normalize_ticker(ticker)
        # period: count 일치 위해 거래일 약 1.5배 캘린더일
        # 안전하게 count*2 + 5 캘린더일 요청
        period_days = max(count * 2 + 5, 30)
        period = f"{period_days}d"
        try:
            t = self._yf.Ticker(symbol)
            hist = t.history(period=period, auto_adjust=False)
        except Exception as e:
            logger.warning(f"[Yahoo] {ticker} history fail: {e}")
            return []

        if hist is None or hist.empty:
            return []

        candles: list[Candle] = []
        for idx, row in hist.iterrows():
            try:
                candles.append(Candle(
                    date=idx.strftime("%Y-%m-%d"),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]) if row["Volume"] else 0,
                ))
            except (ValueError, KeyError):
                continue

        # 최근 count 만 반환
        if len(candles) > count:
            candles = candles[-count:]
        return candles

    async def get_daily_candles(self, ticker: str, count: int | None = None) -> list[Candle]:
        """일봉 데이터 — StooqClient 호환 시그니처."""
        n = count or 252
        candles = await asyncio.to_thread(self._fetch_history_sync, ticker, n)
        logger.info(f"[Yahoo] {ticker} {len(candles)} candles")
        return candles

    async def get_52w_stats(self, ticker: str) -> FiftyTwoWeekStats:
        """52주 통계."""
        candles = await self.get_daily_candles(ticker, count=252)
        if not candles:
            from backend.discovery.data_sources.base import DataSourceError
            raise DataSourceError(f"Yahoo: 52w stats unavailable for {ticker}")

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
        candles = await self.get_daily_candles(ticker, count=1)
        if not candles:
            from backend.discovery.data_sources.base import DataSourceError
            raise DataSourceError(f"Yahoo: current price unavailable for {ticker}")
        return candles[-1].close

    async def get_returns(
        self,
        ticker: str,
        periods: tuple[int, ...] = (21, 63, 126),
    ) -> dict[str, float]:
        max_days = max(periods)
        candles = await self.get_daily_candles(ticker, count=max_days + 1)
        labels = {21: "1m", 63: "3m", 126: "6m", 252: "1y"}
        if not candles:
            return {labels.get(n, f"{n}d"): 0.0 for n in periods}
        current = candles[-1].close
        returns: dict[str, float] = {}
        for n in periods:
            if len(candles) <= n:
                returns[labels.get(n, f"{n}d")] = 0.0
                continue
            past = candles[-1 - n].close
            returns[labels.get(n, f"{n}d")] = (current - past) / past if past > 0 else 0.0
        return returns

    async def get_market_cap(self, ticker: str) -> Optional[float]:
        """Yahoo 'info' 에서 marketCap 추출 (Finnhub 대비 정확도 높음)."""
        symbol = self._normalize_ticker(ticker)
        def _sync():
            try:
                return self._yf.Ticker(symbol).info.get("marketCap")
            except Exception:
                return None
        val = await asyncio.to_thread(_sync)
        return float(val) if val else None
