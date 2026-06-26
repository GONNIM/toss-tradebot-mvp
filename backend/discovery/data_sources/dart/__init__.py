"""DART OpenAPI — 한국 공시 catalyst 시그널 (Phase 3-B).

대상 공시 유형:
- B: 주요사항보고 (자본조정/감자/증자/M&A/관리종목 등) — catalyst 가장 강함
- C: 발행공시 (유상증자/CB)
- D: 지분공시 (임원/주요주주 변동)
- I: 거래소공시 (거래정지/관리종목 지정 — 변동성 폭증)

데이터 흐름:
1. corp_code 매핑 1회 다운로드 (월간 갱신)
2. 매시간 최근 공시 fetch
3. stock_code 별 24h 공시 건수 → catalyst_score 산출
"""
from backend.discovery.data_sources.dart.client import (
    DartDisclosure,
    fetch_corp_codes,
    fetch_recent_disclosures,
    is_configured,
)

__all__ = [
    "DartDisclosure",
    "fetch_corp_codes",
    "fetch_recent_disclosures",
    "is_configured",
]
