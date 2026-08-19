"""금융업 자동 감지 · KSIC 표준산업분류 코드 기반 (v1.0.5 · 2026-08-19).

원칙 4 (재무건전성) 예외 처리용.

기존 (v1.0.2): FDR industry_name keyword 매칭 → FDR 반환값에 산업 컬럼 없어 항상 False
개편 (v1.0.5): DART 기업개황 API induty_code 캐시 · KSIC 대분류 K = 금융업

KSIC 대분류 K (금융 및 보험업):
  64xxx · 금융업 (은행·저축은행·기타 금융)
  65xxx · 보험 및 연금업
  66xxx · 금융 및 보험 관련 서비스업
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.principles.charter import get_manual_override_financial_sector

logger = logging.getLogger(__name__)


# KSIC 금융업 대분류 (2자리 접두)
_FINANCIAL_KSIC_PREFIXES = ("64", "65", "66")


@dataclass(frozen=True)
class SectorInfo:
    ticker: str
    industry_code: Optional[str]
    is_financial_sector: bool
    source: str  # "manual_override" | "ksic" | "unknown"


def is_financial_ksic(induty_code: Optional[str]) -> bool:
    """KSIC 5자리 코드 → 금융업 여부 (대분류 K · 64·65·66)."""
    if not induty_code:
        return False
    return induty_code[:2] in _FINANCIAL_KSIC_PREFIXES


def detect_financial(ticker: str, induty_code: Optional[str]) -> SectorInfo:
    """티커 · KSIC induty_code → SectorInfo.

    조회 순서:
      1. manual_overrides.financial_sector.entries · 있으면 그 값 강제
      2. induty_code 첫 2자리 in {64, 65, 66} → True
      3. 나머지 False
    """
    override = get_manual_override_financial_sector(ticker)
    if override is not None:
        return SectorInfo(
            ticker=ticker,
            industry_code=induty_code,
            is_financial_sector=override,
            source="manual_override",
        )

    if induty_code:
        return SectorInfo(
            ticker=ticker,
            industry_code=induty_code,
            is_financial_sector=is_financial_ksic(induty_code),
            source="ksic",
        )

    return SectorInfo(
        ticker=ticker,
        industry_code=None,
        is_financial_sector=False,
        source="unknown",
    )
