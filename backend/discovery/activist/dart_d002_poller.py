"""한국 DART D002 임원·주요주주 소유상황보고서 폴러 · Phase E.

목적: Phase A/B 에서 감지된 activism 진입 종목의 **임원 매매(insider)** 신호 관찰.
활동주주 진입 후 임원이 대량 매수 (동조) 또는 매도 (이탈) 하는 방향성이 매매 판단에 유용.

pblntf_ty=D · pblntf_detail_ty=D002 (임원·주요주주특정증권등소유상황보고서).
필터: [[state.kr_insider_watchlist]] 로 최근 90일 KR activism 진입 종목 stock_code 만.

이 폴러는 activism watchlist 유지형 · Universe(filer) 매칭 없음.
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

logger = logging.getLogger(__name__)

_DAYS_BACK = 7  # 최근 N일 D002 조회


def _guess_direction(report_nm: str) -> str:
    """report_nm 문자열로 매매 방향 근사.

    Returns: "BUY" | "SELL" | "CHANGE" | "UNKNOWN"
    """
    if not report_nm:
        return "UNKNOWN"
    # DART 예:
    #   "임원ㆍ주요주주특정증권등소유상황보고서"
    #   실제 매매 방향은 문서 내부 · report_nm 만으로는 판정 어려움
    #   → 감지만 알림 · 사용자에게 상세 확인 요구
    return "CHANGE"


@dataclass(frozen=True)
class KrInsiderDisclosure:
    disclosure: DartDisclosure
    stock_code: str
    direction: str   # BUY | SELL | CHANGE | UNKNOWN


async def poll_new_insider_reports(
    watchlist_stock_codes: List[str],
    is_seen_fn,   # callable (key: str, accession: str) -> bool
) -> List[KrInsiderDisclosure]:
    """최근 7일 D002 조회 → watchlist 매칭 → 신규만 반환.

    Args:
        watchlist_stock_codes: activism 진입 종목 KRX 코드 리스트 (6자리)
        is_seen_fn: dedup 콜백 (filer_key='insider' 로 전달)
    """
    if not is_configured():
        return []
    if not watchlist_stock_codes:
        return []

    end_de = date.today()
    bgn_de = end_de - timedelta(days=_DAYS_BACK)

    try:
        disclosures = await fetch_recent_disclosures(
            bgn_de=bgn_de,
            end_de=end_de,
            pblntf_ty="D",
            pblntf_detail_ty="D002",
            only_listed=True,
        )
    except Exception as e:
        logger.warning(f"[activist.insider.kr] DART fetch 실패: {e}")
        return []

    watch = {code for code in watchlist_stock_codes if code}
    matched: List[KrInsiderDisclosure] = []
    for d in disclosures:
        if not d.stock_code or d.stock_code not in watch:
            continue
        if not d.rcept_no:
            continue
        # dedup key = "insider_kr" (특수 filer key)
        if is_seen_fn("insider_kr", d.rcept_no):
            continue
        matched.append(KrInsiderDisclosure(
            disclosure=d,
            stock_code=d.stock_code,
            direction=_guess_direction(d.report_nm),
        ))
    return matched
