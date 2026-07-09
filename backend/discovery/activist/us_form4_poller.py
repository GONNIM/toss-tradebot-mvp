"""미국 SEC Form 4 폴러 · Phase F.

목적: Phase A 에서 감지된 US activism 진입 회사의 **임원·주요주주 매매(Form 4)** 감시.
활동주주 진입 후 임원 매매 방향은 동조/이탈 판단에 유용.

Form 4 = 임원·이사·10%+ 주주 매매 신고 · T+2 영업일.
데이터: data.sec.gov/submissions/CIK{cik}.json 에서 form=="4" 필터.

매수/매도 방향은 XML 파싱 필요 (transactionAcquiredDisposedCode: A=매수, D=매도).
초기 구현: 감지만 · 방향 판정은 XML fetch 추가 (스코프 관리로 감지 우선).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx

from backend.discovery.vip.activist_tracker import fetch_recent as fetch_recent_filings

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 10.0
_RECENT_DAYS = 7    # 최근 N일 이내 Form 4 만 알림 대상
_FORM4_XML_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True)
class Form4Filing:
    subject_cik: str          # 대상 회사 CIK
    subject_ticker: str
    subject_name: str
    accession: str            # SEC accession (예: 0001234-24-000123)
    form: str
    filing_date: str
    primary_desc: str
    direction: str = "UNKNOWN"   # A(매수) | D(매도) | MIXED | UNKNOWN
    reporter_name: str = ""      # 신고 임원 이름 (XML 파싱 후)
    total_value_usd: Optional[float] = None   # 매매 총액 (XML 파싱 후 · 선택)


def _is_recent(filing_date: str) -> bool:
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d").date()
        return (date.today() - d).days <= _RECENT_DAYS
    except (TypeError, ValueError):
        return False


def _accession_url_path(cik: str, accession: str) -> str:
    """SEC Archives URL 조합."""
    cik_num = str(cik).lstrip("0") or "0"
    acc_no_dashes = accession.replace("-", "")
    return f"{_FORM4_XML_BASE}/{cik_num}/{acc_no_dashes}"


async def _fetch_form4_xml(cik: str, accession: str, ua: str) -> Optional[bytes]:
    """Form 4 primary XML 다운로드. 파일명 규칙: {accession}-index.json → primary_doc 찾기.

    간단화: index.json 조회로 XML 파일명 확인 후 다운로드.
    """
    idx_url = f"{_accession_url_path(cik, accession)}/{accession}-index.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(idx_url, headers={"User-Agent": ua})
            resp.raise_for_status()
            idx = resp.json()
    except Exception as e:
        logger.debug(f"[form4] index fetch 실패 {accession}: {e}")
        return None

    # 첫 .xml 파일 찾기 (통상 primary_doc.xml 또는 wf-form4-*.xml)
    items = idx.get("directory", {}).get("item") or []
    xml_name = None
    for it in items:
        name = it.get("name", "")
        if name.endswith(".xml") and not name.endswith("-index.xml"):
            xml_name = name
            break
    if not xml_name:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(
                f"{_accession_url_path(cik, accession)}/{xml_name}",
                headers={"User-Agent": ua},
            )
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.debug(f"[form4] XML fetch 실패 {accession}: {e}")
        return None


def _parse_form4(xml_bytes: bytes) -> tuple[str, str, Optional[float]]:
    """Form 4 XML 에서 방향 · reporter · 총 매매액 추출.

    Returns: (direction, reporter_name, total_value_usd)
      direction: "A" (all acquired) | "D" (all disposed) | "MIXED" | "UNKNOWN"
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return "UNKNOWN", "", None

    # reporter
    reporter_name = ""
    for tag in root.iter("rptOwnerName"):
        if tag.text:
            reporter_name = tag.text.strip()
            break

    # transaction 방향 · 총액
    directions = []
    total = 0.0
    for txn in root.iter("nonDerivativeTransaction"):
        code_elem = txn.find(".//transactionAcquiredDisposedCode/value")
        code = code_elem.text.strip() if code_elem is not None and code_elem.text else ""
        if code in ("A", "D"):
            directions.append(code)
        shares_elem = txn.find(".//transactionShares/value")
        price_elem = txn.find(".//transactionPricePerShare/value")
        try:
            shares = float(shares_elem.text) if shares_elem is not None and shares_elem.text else 0.0
            price = float(price_elem.text) if price_elem is not None and price_elem.text else 0.0
            total += shares * price
        except (TypeError, ValueError):
            pass

    if not directions:
        direction = "UNKNOWN"
    elif all(d == "A" for d in directions):
        direction = "A"
    elif all(d == "D" for d in directions):
        direction = "D"
    else:
        direction = "MIXED"

    return direction, reporter_name, (total if total > 0 else None)


async def poll_new_form4(
    watchlist: List[dict],   # [{ticker, cik, name}, ...]
    ua: str,
    is_seen_fn,              # (subject_cik, accession) -> bool
    parse_xml: bool = True,
) -> List[Form4Filing]:
    """Watchlist 회사의 Form 4 · 최근 7일 · 신규만 반환. parse_xml=True 시 방향 파싱 (부담↑)."""
    results: List[Form4Filing] = []
    for w in watchlist:
        cik = w.get("cik")
        ticker = w.get("ticker")
        name = w.get("name") or ""
        if not cik or not ticker:
            continue
        try:
            filings = await fetch_recent_filings(cik, ua)
        except Exception as e:
            logger.warning(f"[form4] {cik} fetch 실패: {e}")
            continue

        for f in filings:
            if f.form != "4":
                continue
            if not _is_recent(f.filing_date):
                continue
            if not f.accession:
                continue
            if is_seen_fn(cik, f.accession):
                continue

            direction = "UNKNOWN"
            reporter_name = ""
            total_value = None
            if parse_xml:
                xml_bytes = await _fetch_form4_xml(cik, f.accession, ua)
                if xml_bytes:
                    direction, reporter_name, total_value = _parse_form4(xml_bytes)

            results.append(Form4Filing(
                subject_cik=cik,
                subject_ticker=ticker,
                subject_name=name,
                accession=f.accession,
                form=f.form,
                filing_date=f.filing_date,
                primary_desc=f.primary_desc or "",
                direction=direction,
                reporter_name=reporter_name,
                total_value_usd=total_value,
            ))
    return results
