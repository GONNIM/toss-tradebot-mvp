"""KRX 산업분류 → 금융업 자동 감지 · manual_overrides 통합 (v1.0.2).

원칙 4 (재무건전성) 예외 처리용.
FDR StockListing 의 Sector 필드 기반 · KRX 표준산업분류 상 금융업 키워드 매칭.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.principles.charter import get_manual_override_financial_sector

logger = logging.getLogger(__name__)


# KRX 산업분류 상 금융업 · 은행업 · 증권업 · 보험업 · 여신금융 · 신용카드 · 자산운용 등
_FINANCIAL_KEYWORDS = (
    "은행",
    "증권",
    "보험",
    "여신금융",
    "여전",
    "종합금융",
    "자산운용",
    "카드",
    "금융지주",
    "저축은행",
    "선물",
    "투자자문",
)


@dataclass(frozen=True)
class SectorInfo:
    ticker: str
    industry_code: Optional[str]
    industry_name: Optional[str]
    is_financial_sector: bool
    source: str  # "auto" | "manual_override"


def detect_financial(ticker: str, industry_name: Optional[str]) -> SectorInfo:
    """티커 · 산업명 → SectorInfo.

    조회 순서:
      1. manual_overrides.financial_sector.entries · 있으면 그 값 강제
      2. FDR industry_name 에 금융업 키워드 매칭 · 있으면 True
      3. 나머지 False
    """
    override = get_manual_override_financial_sector(ticker)
    if override is not None:
        return SectorInfo(
            ticker=ticker,
            industry_code=None,
            industry_name=industry_name,
            is_financial_sector=override,
            source="manual_override",
        )

    is_fin = False
    if industry_name:
        low = industry_name.strip()
        for kw in _FINANCIAL_KEYWORDS:
            if kw in low:
                is_fin = True
                break

    return SectorInfo(
        ticker=ticker,
        industry_code=None,
        industry_name=industry_name,
        is_financial_sector=is_fin,
        source="auto",
    )
