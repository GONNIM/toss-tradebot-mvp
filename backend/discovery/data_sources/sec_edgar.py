"""SEC EDGAR 클라이언트 — F6 인사이더 매수 (결정 41).

- 무료 공식 API
- Form 4 (insider transactions) 조회
- 핵심: 15일 내 cluster buy (3명 이상) 검출

학술 검증 (moonshot-factor-research.md §1.2):
- 3+ insiders cluster within 15 days → 12m above-market returns
- 단독 insider buy → 연 +4~8% excess return

데이터 흐름:
1. ticker → CIK (company concept tickers JSON)
2. CIK → 최근 Form 4 filings (submissions API)
3. 각 filing XML 파싱 → 매수·매도 + 수량 + 가격

User-Agent 헤더 필수 (SEC 정책): "회사명 이메일"
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from backend.discovery.data_sources.base import DataSourceClient, DataSourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InsiderFiling:
    """Form 4 단일 거래 요약."""

    cik: str
    ticker: str
    insider_name: str
    insider_title: Optional[str]
    transaction_type: str  # 'P' (Purchase) / 'S' (Sale)
    shares: float
    price_per_share: Optional[float]
    transaction_date: str  # YYYY-MM-DD
    filed_date: str
    accession: str


@dataclass(frozen=True)
class InsiderClusterStats:
    """클러스터 매수 통계 — F6 인자 입력."""

    ticker: str
    window_days: int  # 15
    distinct_buyers: int
    total_buy_filings: int
    total_buy_shares: float
    cluster_detected: bool  # ≥ 3 insiders within window
    most_recent_filed: Optional[str]


class SECEdgarClient(DataSourceClient):
    """SEC EDGAR Form 4 클라이언트.

    User-Agent 정책: https://www.sec.gov/os/accessing-edgar-data
    """

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self) -> None:
        # SEC EDGAR User-Agent 정책 — 회사명·이메일 필수
        contact = os.environ.get(
            "SEC_USER_AGENT",
            "toss-tradebot-mvp/0.1 (sample@example.com)",
        )
        super().__init__(
            base_url=self.BASE_URL,
            headers={
                "User-Agent": contact,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self._ticker_to_cik: dict[str, str] = {}  # 캐시

    async def _load_ticker_map(self) -> dict[str, str]:
        """SEC 공개 ticker → CIK 매핑 다운로드 (전체, ~1MB)."""
        if self._ticker_to_cik:
            return self._ticker_to_cik

        response = await self.get("/files/company_tickers.json")
        data = response.json()

        # 응답 형식: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = entry.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = str(cik).zfill(10)  # 10자리 0-pad

        self._ticker_to_cik = mapping
        logger.info(f"[SEC] loaded {len(mapping)} ticker→CIK mappings")
        return mapping

    async def get_cik(self, ticker: str) -> Optional[str]:
        """ticker → CIK (10자리 0-padded)."""
        mapping = await self._load_ticker_map()
        return mapping.get(ticker.upper())

    async def get_recent_form4_filings(
        self,
        ticker: str,
        within_days: int = 15,
    ) -> list[InsiderFiling]:
        """최근 N일 Form 4 filing 조회 (간이 — submissions API 활용).

        Note:
        - SEC submissions API: data.sec.gov/submissions/CIK{NNNNNNNNNN}.json
        - 본 메소드는 filing list 메타데이터만 수집 (full XML 파싱은 향후).
        - 정확한 transaction_type/shares 는 Form 4 XML 추가 fetch 필요 (Phase D 정밀화 후보).
        """
        cik = await self.get_cik(ticker)
        if not cik:
            logger.warning(f"[SEC] CIK not found for ticker {ticker}")
            return []

        # data.sec.gov 호스트 변경 (base_url 임시 override)
        # 같은 클라이언트 재사용 위해 절대 URL 사용
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        response = await self._client.get(url) if self._client else None  # type: ignore
        if response is None:
            raise DataSourceError("SEC client not entered")
        response.raise_for_status()
        data = response.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = (datetime.now() - timedelta(days=within_days)).strftime("%Y-%m-%d")

        filings: list[InsiderFiling] = []
        for i, form in enumerate(forms):
            if form != "4":
                continue
            filed = filing_dates[i] if i < len(filing_dates) else ""
            if filed < cutoff:
                continue
            accession = accessions[i] if i < len(accessions) else ""

            # 단순화: 실 XML 파싱 없이 메타데이터만 — 향후 정밀화
            filings.append(
                InsiderFiling(
                    cik=cik,
                    ticker=ticker.upper(),
                    insider_name="(parse XML for name)",  # Phase D 정밀화
                    insider_title=None,
                    transaction_type="?",  # 'P' or 'S' — XML 파싱 필요
                    shares=0.0,
                    price_per_share=None,
                    transaction_date=filed,
                    filed_date=filed,
                    accession=accession,
                )
            )

        logger.info(f"[SEC] {ticker} {len(filings)} Form 4 filings within {within_days}d")
        return filings

    async def get_cluster_stats(
        self,
        ticker: str,
        window_days: int = 15,
    ) -> InsiderClusterStats:
        """클러스터 매수 통계 (F6 인자용).

        주의: 현재는 filing count 기반 근사 — distinct_buyers 정확 측정은
        Form 4 XML 파싱 필요 (Phase D 정밀화).
        """
        filings = await self.get_recent_form4_filings(ticker, within_days=window_days)

        # 근사: filing 수 → 보수적 distinct_buyers 추정 (1 filing ≈ 1 buyer)
        distinct_buyers = len({f.accession for f in filings})  # 임시
        total_buys = len(filings)  # transaction_type 미파악 시 전체

        most_recent = max((f.filed_date for f in filings), default=None)

        return InsiderClusterStats(
            ticker=ticker.upper(),
            window_days=window_days,
            distinct_buyers=distinct_buyers,
            total_buy_filings=total_buys,
            total_buy_shares=0.0,  # XML 파싱 후 채움
            cluster_detected=distinct_buyers >= 3,
            most_recent_filed=most_recent,
        )
