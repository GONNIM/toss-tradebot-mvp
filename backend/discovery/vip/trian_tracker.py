"""Trian Fund Management L.P. (CIK 0001345471) SEC 필링 트래커.

data.sec.gov/submissions/CIK{cik}.json 폴링 → 최근 필링 중 신규 accession 감지.
관심 폼: SC 13D, SC 13D/A, SC 13G, SC 13G/A (액티비스트 지분 신고).
Form 4 (내부자 매매) 는 Trian 이 director 로 등재된 여러 회사에서 대량 발생하므로
P-A 스코프에서는 제외 — WEN 관련 여부 판단 없이 발송하면 노이즈.

WEN 관련 여부 필터:
- primaryDocDescription 또는 상세 필링 이슈어에서 "WEN" / "WENDY" 매치.
- 데이터 소스에서 subject company 를 직접 주지 않는 경우가 있어, description
  기반 문자열 매치로 근사. 오검출을 감수하고도 "실제 WEN 필링" 을 놓치지 않는 게 우선.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://data.sec.gov/submissions"
_TIMEOUT_SEC = 10.0

# 폼 필터 — 액티비스트 지분 신고 계열만.
_INTEREST_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}

# WEN 관련 여부 판정에 쓸 문자열 (대소문자 무시).
_WEN_KEYWORDS = ("WEN", "WENDY")


@dataclass(frozen=True)
class Filing:
    accession: str        # accessionNumber (e.g. 0001345471-24-000012)
    form: str
    filing_date: str      # ISO date
    primary_doc: str
    primary_desc: str


def _matches_wen(desc: str) -> bool:
    up = desc.upper()
    return any(kw in up for kw in _WEN_KEYWORDS)


async def fetch_recent(cik: str, ua: str) -> List[Filing]:
    """Trian CIK 의 최근 필링(recent) 목록 반환.

    실패 시 빈 리스트 — 상위 job 이 다음 tick 에서 재시도.
    """
    padded = str(cik).lstrip("0").zfill(10)
    url = f"{_BASE}/CIK{padded}.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(url, headers={"User-Agent": ua})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[vip.trian] fetch 실패 CIK={cik}: {e}")
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [])

    result: List[Filing] = []
    for i in range(len(forms)):
        result.append(
            Filing(
                accession=accs[i] if i < len(accs) else "",
                form=forms[i],
                filing_date=dates[i] if i < len(dates) else "",
                primary_doc=docs[i] if i < len(docs) else "",
                primary_desc=descs[i] if i < len(descs) else "",
            )
        )
    return result


def latest_wen_filing(filings: List[Filing]) -> Optional[Filing]:
    """관심 폼 & WEN 관련 문자열 매치 중 가장 최신 필링 (recent 순서 첫 항목).

    data.sec.gov 응답은 최신 필링이 인덱스 0. WEN 필터는 desc 기반 근사.
    """
    for f in filings:
        if f.form not in _INTEREST_FORMS:
            continue
        if _matches_wen(f.primary_desc):
            return f
    return None
