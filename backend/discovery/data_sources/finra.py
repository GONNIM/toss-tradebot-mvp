"""FINRA 단기매도 (Short Interest) 클라이언트 — F1 스퀴즈 인자 (가중 6%).

학술 검증 (moonshot-factor-research.md §1.3):
- Short Squeeze 알파 = 약함 (Diether et al. 2009 → top-decile 익월 -0.5%)
- 우리 가중치 6% (보조 신호)

데이터 소스:
- FINRA OTC short interest reports (bi-monthly, free)
- 또는 Stooq의 short interest 컬럼 (Stooq 미제공 시 fallback)
- 정확한 SI%/days-to-cover 는 NYSE/Nasdaq 직접 fetch 필요

설계:
- FINRA의 "Short Sale Volume" daily file (FTP) — 일일 short volume 비율
- URL: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
- pipe-separated text file
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from backend.discovery.data_sources.base import DataSourceClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShortVolumeData:
    """FINRA 단일 거래일 short volume."""

    ticker: str
    date: str               # YYYY-MM-DD
    short_volume: int
    total_volume: int
    short_ratio: float      # short / total (0.0 ~ 1.0)


@dataclass(frozen=True)
class ShortInterestSummary:
    """최근 N일 short volume 추세 (F1 인자용)."""

    ticker: str
    window_days: int
    avg_short_ratio: float      # 평균 단기매도 비율
    latest_short_ratio: float   # 최신
    trend_up: bool              # 최신 > 평균
    samples: int                # 실제 수집된 거래일 수


class FINRAClient(DataSourceClient):
    """FINRA 단기매도 거래량 클라이언트."""

    BASE_URL = "https://cdn.finra.org"

    # 보드별 파일 prefix
    BOARDS = {
        "consolidated": "CNMSshvol",   # All Tape Codes (가장 광범위)
        "fnsq": "FNSQshvol",           # Nasdaq Carteret
        "fnyx": "FNYXshvol",           # NYSE
    }

    def __init__(self) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            headers={
                "User-Agent": "toss-tradebot-mvp/0.1",
                "Accept": "text/plain",
            },
        )

    async def get_daily_short_volume(
        self,
        date: datetime,
        board: str = "consolidated",
    ) -> dict[str, ShortVolumeData]:
        """단일 거래일 전체 ticker short volume.

        Returns:
            {ticker: ShortVolumeData}
        Note:
            FINRA는 거래일만 제공 — 주말/공휴일 404 가능. 호출 측 retry 필요.
        """
        prefix = self.BOARDS.get(board, "CNMSshvol")
        date_str = date.strftime("%Y%m%d")
        path = f"/equity/regsho/daily/{prefix}{date_str}.txt"

        try:
            response = await self.get(path)
        except Exception as e:
            logger.warning(f"[FINRA] {date_str} fetch failed: {e}")
            return {}

        if response.status_code != 200:
            return {}

        # FINRA 파일 형식 (pipe-separated):
        # Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
        lines = response.text.strip().split("\n")
        if len(lines) < 2:
            return {}

        result: dict[str, ShortVolumeData] = {}
        for line in lines[1:]:  # skip header
            parts = line.split("|")
            if len(parts) < 5:
                continue
            try:
                _date = parts[0]
                ticker = parts[1].strip().upper()
                short_vol = int(parts[2])
                total_vol = int(parts[4])
                ratio = short_vol / total_vol if total_vol > 0 else 0.0

                result[ticker] = ShortVolumeData(
                    ticker=ticker,
                    date=f"{_date[:4]}-{_date[4:6]}-{_date[6:]}",
                    short_volume=short_vol,
                    total_volume=total_vol,
                    short_ratio=ratio,
                )
            except (ValueError, IndexError):
                continue

        logger.info(f"[FINRA] {date_str} {len(result)} tickers loaded")
        return result

    async def get_short_summary(
        self,
        ticker: str,
        window_days: int = 5,
    ) -> ShortInterestSummary:
        """최근 N일 short volume 추세 (F1 인자용)."""
        today = datetime.now()
        ratios: list[float] = []

        for i in range(window_days + 3):  # 주말 여유
            if len(ratios) >= window_days:
                break
            d = today - timedelta(days=i)
            # 주말 skip
            if d.weekday() >= 5:
                continue
            data = await self.get_daily_short_volume(d)
            if not data:
                continue
            entry = data.get(ticker.upper())
            if entry:
                ratios.append(entry.short_ratio)

        if not ratios:
            return ShortInterestSummary(
                ticker=ticker.upper(),
                window_days=window_days,
                avg_short_ratio=0.0,
                latest_short_ratio=0.0,
                trend_up=False,
                samples=0,
            )

        avg = sum(ratios) / len(ratios)
        latest = ratios[0]  # 최신이 index 0 (오늘 → 과거)

        return ShortInterestSummary(
            ticker=ticker.upper(),
            window_days=window_days,
            avg_short_ratio=avg,
            latest_short_ratio=latest,
            trend_up=latest > avg,
            samples=len(ratios),
        )
