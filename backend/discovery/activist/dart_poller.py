"""한국 DART 대량보유상황보고서 폴러 · Phase B.

pblntf_ty=D (지분공시) · pblntf_detail_ty=D001 (대량보유상황보고서) 필터.
flr_nm(제출인) → [[kr_normalizer]] · Universe(country=KR) 매칭.

이 폴러는 SEC 폴러와 병행 · 첫 tick backfill 방어 로직 공유.
보유목적(경영참여/단순투자) 상세 파싱은 report_nm 문자열 판정으로 근사 —
정확한 필터는 후속 iteration 에서 majorstock.json 또는 document.zip 파싱으로 강화.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from backend.discovery.data_sources.dart.client import (
    DartDisclosure,
    fetch_recent_disclosures,
    is_configured,
)

from . import kr_normalizer
from .universe import Activist

logger = logging.getLogger(__name__)

_DAYS_BACK = 7  # 최근 N일 조회


def _guess_purpose(report_nm: str) -> str:
    """report_nm 문자열로 보유목적 근사 판정.

    Returns: "MANAGEMENT" | "PASSIVE" | "UNKNOWN"
    """
    if not report_nm:
        return "UNKNOWN"
    # DART 보고서 제목 예:
    #   "주식등의대량보유상황보고서(일반)"       — 통상 경영참여 목적
    #   "주식등의대량보유상황보고서(약식)"       — 통상 단순투자
    #   "주식등의대량보유상황보고서(변동보고)"
    if "약식" in report_nm:
        return "PASSIVE"
    if "일반" in report_nm or "변동" in report_nm:
        return "MANAGEMENT"
    return "UNKNOWN"


@dataclass(frozen=True)
class KrActivistDisclosure:
    activist: Activist
    disclosure: DartDisclosure
    purpose: str   # MANAGEMENT | PASSIVE | UNKNOWN


async def poll_new_disclosures(
    activists: List[Activist],
    is_seen_fn,   # callable (filer_key: str, accession: str) -> bool
) -> List[KrActivistDisclosure]:
    """최근 7일 D001 공시 조회 → Universe KR 매칭 → 신규만 반환. DART key 없으면 빈 리스트."""
    if not is_configured():
        return []

    end_de = date.today()
    bgn_de = end_de - timedelta(days=_DAYS_BACK)

    try:
        disclosures = await fetch_recent_disclosures(
            bgn_de=bgn_de,
            end_de=end_de,
            pblntf_ty="D",
            pblntf_detail_ty="D001",
            only_listed=True,
        )
    except Exception as e:
        logger.warning(f"[activist.kr] DART fetch 실패: {e}")
        return []

    kr_activists = [a for a in activists if a.country == "KR"]
    if not kr_activists:
        return []

    matched: List[KrActivistDisclosure] = []
    for d in disclosures:
        key = kr_normalizer.match_activist_key(d.flr_nm)
        if not key:
            continue
        activist = next((a for a in kr_activists if a.key == key), None)
        if activist is None:
            continue
        if not d.rcept_no:
            continue
        if is_seen_fn(activist.key, d.rcept_no):
            continue
        matched.append(KrActivistDisclosure(
            activist=activist,
            disclosure=d,
            purpose=_guess_purpose(d.report_nm),
        ))
    return matched
