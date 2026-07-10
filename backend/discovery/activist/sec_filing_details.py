"""SEC SC 13D · SC 13G primary_doc.xml 파싱.

SEC 정형 스키마 (2025~ 개편): http://www.sec.gov/edgar/schedule13D
파일 위치: `Archives/edgar/data/{filer_cik}/{accession_nodash}/primary_doc.xml`

추출 대상 (매매 판단 핵심):
- issuer_name / issuer_cik / issuer_cusip
- securities_class_title (예: "Common Stock, par value $0.0001 per share")
- percent_of_class (예: 31.1) — 지분율 %
- aggregate_amount_owned — 총 보유 주식 수
- amendment_no (예: 11)
- date_of_event
- transaction_purpose_excerpt (item4 발췌 · 최대 400자)

옛날 SC 13D 는 정형 XML 없이 HTML/TXT · 파싱 실패 시 빈 dict.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 10.0
_BASE = "https://www.sec.gov/Archives/edgar/data"

_NS = {
    "s13": "http://www.sec.gov/edgar/schedule13D",
    "cmn": "http://www.sec.gov/edgar/common",
}


@dataclass(frozen=True)
class SC13Details:
    issuer_name: str = ""
    issuer_cik: str = ""
    issuer_cusip: str = ""
    securities_class_title: str = ""
    percent_of_class: Optional[float] = None      # 지분율 (단일 · 최대 값)
    aggregate_amount_owned: Optional[int] = None  # 총 보유 주식 수 (최대 값)
    amendment_no: Optional[int] = None
    date_of_event: str = ""                       # MM/DD/YYYY
    transaction_purpose: str = ""                 # item4 발췌
    reporting_persons_count: int = 0              # 서명 reporting person 수


async def fetch_and_parse(filer_cik: str, accession: str, ua: str) -> Optional[SC13Details]:
    """SC 13D/G primary_doc.xml 파싱. 실패 시 None."""
    if not filer_cik or not accession:
        return None
    cik_num = str(filer_cik).lstrip("0") or "0"
    acc_no_dashes = accession.replace("-", "")
    url = f"{_BASE}/{cik_num}/{acc_no_dashes}/primary_doc.xml"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(url, headers={"User-Agent": ua})
            resp.raise_for_status()
            content = resp.content
    except Exception as e:
        logger.debug(f"[sc13.parse] fetch 실패 {accession}: {e}")
        return None
    try:
        return _parse(content)
    except Exception as e:
        logger.debug(f"[sc13.parse] parse 실패 {accession}: {e}")
        return None


def _text(root, path: str, ns=None) -> str:
    node = root.find(path, ns or _NS)
    if node is not None and node.text:
        return node.text.strip()
    return ""


def _findall_text(root, path: str, ns=None) -> list:
    return [
        (n.text or "").strip()
        for n in root.findall(path, ns or _NS)
        if n.text
    ]


def _parse(xml_bytes: bytes) -> SC13Details:
    root = ET.fromstring(xml_bytes)

    issuer_name = _text(root, ".//s13:coverPageHeader/s13:issuerInfo/s13:issuerName")
    issuer_cik = _text(root, ".//s13:coverPageHeader/s13:issuerInfo/s13:issuerCIK")
    issuer_cusip = _text(root, ".//s13:coverPageHeader/s13:issuerInfo/s13:issuerCusips/s13:issuerCusipNumber")
    class_title = _text(root, ".//s13:coverPageHeader/s13:securitiesClassTitle")

    # amendmentNo · dateOfEvent
    amend_txt = _text(root, ".//s13:coverPageHeader/s13:amendmentNo")
    amendment_no: Optional[int] = None
    if amend_txt:
        try:
            amendment_no = int(amend_txt)
        except ValueError:
            pass
    date_of_event = _text(root, ".//s13:coverPageHeader/s13:dateOfEvent")

    # reportingPersons · percentOfClass 및 aggregateAmountOwned 최대 값
    pcs = _findall_text(root, ".//s13:reportingPersons//s13:percentOfClass")
    aggs = _findall_text(root, ".//s13:reportingPersons//s13:aggregateAmountOwned")
    reporting_count = len(root.findall(".//s13:reportingPersons/s13:reportingPersonInfo", _NS))

    def _max_float(vals):
        out = []
        for v in vals:
            try:
                out.append(float(v))
            except ValueError:
                continue
        return max(out) if out else None

    def _max_int(vals):
        out = []
        for v in vals:
            try:
                out.append(int(float(v)))
            except ValueError:
                continue
        return max(out) if out else None

    percent_of_class = _max_float(pcs)
    aggregate_amount_owned = _max_int(aggs)

    # item 4 발췌
    purpose = _text(root, ".//s13:items1To7/s13:item4/s13:transactionPurpose")
    if len(purpose) > 400:
        purpose = purpose[:397] + "..."

    return SC13Details(
        issuer_name=issuer_name,
        issuer_cik=issuer_cik,
        issuer_cusip=issuer_cusip,
        securities_class_title=class_title,
        percent_of_class=percent_of_class,
        aggregate_amount_owned=aggregate_amount_owned,
        amendment_no=amendment_no,
        date_of_event=date_of_event,
        transaction_purpose=purpose,
        reporting_persons_count=reporting_count,
    )
