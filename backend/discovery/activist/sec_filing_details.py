"""SEC SC 13D · SC 13G primary_doc.xml 파싱.

SEC 정형 스키마:
- SC 13D: http://www.sec.gov/edgar/schedule13D  (대문자 D)
- SC 13G: http://www.sec.gov/edgar/schedule13g  (소문자 g)

v1.53 · P2-5 · URI-agnostic XPath (`.//{{*}}elementName`) 사용 · form별 URI 분기 불필요.
Python ElementTree 3.8+ 지원 · SC 13D/G 모두 하나의 로직으로 파싱.

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


def _text(root, path: str) -> str:
    """v1.53 · URI-agnostic · path 는 `.//{{*}}elementName` 형태 사용."""
    node = root.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return ""


def _findall_text(root, path: str) -> list:
    return [
        (n.text or "").strip()
        for n in root.findall(path)
        if n.text
    ]


def _parse(xml_bytes: bytes) -> SC13Details:
    root = ET.fromstring(xml_bytes)

    # v1.53 · P2-5 · URI-agnostic XPath (`{*}` 로 URI 무시)
    #   원 · s13:issuerName 은 schedule13D URI 만 매칭 · SC 13G(소문자 g) 실패
    #   개선 · {*}issuerName 은 모든 URI 매칭 · SC 13D/G 통합 파싱
    issuer_name = _text(root, ".//{*}coverPageHeader/{*}issuerInfo/{*}issuerName")
    issuer_cik = _text(root, ".//{*}coverPageHeader/{*}issuerInfo/{*}issuerCIK")
    issuer_cusip = _text(root, ".//{*}coverPageHeader/{*}issuerInfo/{*}issuerCusips/{*}issuerCusipNumber")
    class_title = _text(root, ".//{*}coverPageHeader/{*}securitiesClassTitle")

    # amendmentNo · dateOfEvent
    amend_txt = _text(root, ".//{*}coverPageHeader/{*}amendmentNo")
    amendment_no: Optional[int] = None
    if amend_txt:
        try:
            amendment_no = int(amend_txt)
        except ValueError:
            pass
    date_of_event = _text(root, ".//{*}coverPageHeader/{*}dateOfEvent")

    # reportingPersons · percentOfClass 및 aggregateAmountOwned 최대 값
    pcs = _findall_text(root, ".//{*}reportingPersons//{*}percentOfClass")
    aggs = _findall_text(root, ".//{*}reportingPersons//{*}aggregateAmountOwned")
    reporting_count = len(root.findall(".//{*}reportingPersons/{*}reportingPersonInfo"))

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
    purpose = _text(root, ".//{*}items1To7/{*}item4/{*}transactionPurpose")
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
