"""미국 SEC EDGAR SC 13D/G 폴러 · Phase A.

기존 [[vip.activist_tracker]] 의 fetch_recent(cik, ua) 함수 재활용.
Universe CIK 순회하며 신규 accession 감지.

관심 폼: SC 13D · SC 13D/A · SC 13G · SC 13G/A · SCHEDULE 13D · SCHEDULE 13D/A

날짜 필터: filing_date 가 최근 7일 이내인 것만 실 알림 대상 (오래된 backfill 방어).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from backend.discovery.vip.activist_tracker import Filing, fetch_recent

from .universe import Activist

logger = logging.getLogger(__name__)

_INTEREST_FORMS = {
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
}
_RECENT_DAYS = 7   # 이 기간 초과 필링은 알림 대상 아님 (state 만 mark)


def _is_recent(filing_date: str) -> bool:
    """filing_date (YYYY-MM-DD) 가 최근 _RECENT_DAYS 이내인가."""
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d").date()
        return (date.today() - d).days <= _RECENT_DAYS
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ActivistFiling:
    activist: Activist
    filing: Filing
    is_recent: bool = False


async def poll_new_filings(
    activists: List[Activist],
    ua: str,
    is_seen_fn,   # callable (filer_key: str, accession: str) -> bool
) -> List[ActivistFiling]:
    """전 activist 순회 · 신규 관심 폼 필링만 반환. is_recent 로 알림 대상 표시."""
    results: List[ActivistFiling] = []
    for a in activists:
        if a.country != "US" or not a.cik:
            continue
        try:
            filings = await fetch_recent(a.cik, ua)
        except Exception as e:
            logger.warning(f"[activist.sec] {a.key} fetch 실패: {e}")
            continue

        for f in filings:
            if f.form not in _INTEREST_FORMS:
                continue
            if not f.accession:
                continue
            if is_seen_fn(a.key, f.accession):
                continue
            results.append(ActivistFiling(
                activist=a,
                filing=f,
                is_recent=_is_recent(f.filing_date),
            ))
    return results
