"""Activist SEC 필링 트래커 (VIP-agnostic).

data.sec.gov/submissions/CIK{cik}.json 폴링 → 최근 필링 중 대상 회사 매치 감지.
관심 폼: SC 13D, SC 13D/A, SC 13G, SC 13G/A (액티비스트 지분 신고).
Form 4 (내부자 매매) 는 다수 회사에서 대량 발생 → 대상 회사 문자열 필터 없으면
노이즈. 관심 폼만 유지.

대상 회사 판정: primaryDocDescription 문자열에 keywords 중 하나가 포함되면 매치.
오검출은 감수하고도 실제 대상 필링을 놓치지 않는 게 우선 (5분 폴링, dedup 있음).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://data.sec.gov/submissions"
_TIMEOUT_SEC = 10.0

_INTEREST_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: str
    primary_doc: str
    primary_desc: str


def _matches_target(desc: str, keywords: Sequence[str]) -> bool:
    if not keywords:
        return False
    up = desc.upper()
    return any(kw and kw in up for kw in keywords)


async def fetch_recent(cik: str, ua: str) -> List[Filing]:
    """activist CIK 의 recent 필링 리스트. 실패 시 빈 리스트."""
    if not cik:
        return []
    padded = str(cik).lstrip("0").zfill(10)
    url = f"{_BASE}/CIK{padded}.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(url, headers={"User-Agent": ua})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[vip.activist] fetch 실패 CIK={cik}: {e}")
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [])

    return [
        Filing(
            accession=accs[i] if i < len(accs) else "",
            form=forms[i],
            filing_date=dates[i] if i < len(dates) else "",
            primary_doc=docs[i] if i < len(docs) else "",
            primary_desc=descs[i] if i < len(descs) else "",
        )
        for i in range(len(forms))
    ]


def latest_target_filing(
    filings: List[Filing], keywords: Sequence[str]
) -> Optional[Filing]:
    """관심 폼 + 대상 keywords 매치 중 가장 최신 필링."""
    for f in filings:
        if f.form not in _INTEREST_FORMS:
            continue
        if _matches_target(f.primary_desc, keywords):
            return f
    return None
